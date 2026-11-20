import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent.parent


class DevelopmentTests(unittest.TestCase):
    def test_loopback_server_does_not_depend_on_reverse_dns(self):
        from clipmac.server import LocalHTTPServer
        from http.server import BaseHTTPRequestHandler
        with patch('socket.getfqdn', side_effect=AssertionError('reverse DNS must not be required')):
            with LocalHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler) as server:
                self.assertEqual(server.server_name, 'localhost')
                self.assertGreater(server.server_port, 0)

    def execute(self, code, directory, dev='1'):
        return subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                              env={**os.environ, 'CLIPMAC_DEV': dev, 'CLIPMAC_DATA_DIR': str(directory)},
                              text=True, capture_output=True, timeout=20)

    def test_live_data_directory_override_is_respected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = self.execute('from clipmac.state import RUNTIME; print(RUNTIME)', temp, dev='0')
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(Path(p.stdout.strip()), Path(temp).resolve())

    def test_development_rejects_nonempty_unmarked_directory_without_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp)/'queue.sqlite'; marker.write_bytes(b'untouched')
            p = self.execute('import clipmac.state', temp)
            self.assertNotEqual(p.returncode, 0)
            self.assertEqual(marker.read_bytes(), b'untouched')
            self.assertEqual(list(Path(temp).iterdir()), [marker])

    def test_development_rejects_credentials_even_in_marked_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/'.clipmac-development').touch()
            (Path(temp)/'credentials').mkdir()
            p = self.execute('import clipmac.state', temp)
            self.assertNotEqual(p.returncode, 0)

    def test_live_launcher_cannot_open_an_existing_production_dashboard_in_dev_mode(self):
        code = '''
from unittest.mock import patch
from clipmac import launch
with patch.object(launch, 'reachable') as reachable, patch.object(launch.webbrowser, 'open') as browser:
    try: launch.main()
    except RuntimeError as e: assert 'clipmac.dev' in str(e)
    else: raise AssertionError('live launcher accepted development mode')
    reachable.assert_not_called()
    browser.assert_not_called()
'''
        with tempfile.TemporaryDirectory() as temp:
            p = self.execute(code, temp)
            self.assertEqual(p.returncode, 0, p.stderr)

    def test_low_level_external_actions_are_blocked_before_using_dependencies(self):
        code = '''
from unittest.mock import MagicMock
from clipmac import publisher, tiktok
from clipmac.engine import Engine
from clipmac.tiktok_service import TikTokController
from clipmac.state import Store, settings, secrets
assert settings()['publish_enabled'] is False
assert settings()['channel_id'] == ''
assert secrets() == {}
store = Store()
calls = [lambda: publisher.upload(MagicMock(), {}), publisher.connect,
         lambda: publisher.save_client({}), lambda: publisher.service_for_channel('anything'),
         lambda: tiktok.publish('demo', 'id', session=MagicMock()),
         lambda: tiktok.post_once(MagicMock()),
         lambda: TikTokController(store).start('check'),
         lambda: Engine(store).start(), lambda: Engine(store).discover()]
for call in calls:
    try: call()
    except RuntimeError as e: assert 'Entwicklungsmodus' in str(e)
    else: raise AssertionError('external action was not blocked')
with_error = False
try:
    with tiktok.browser(): pass
except RuntimeError: with_error = True
assert with_error
'''
        with tempfile.TemporaryDirectory() as temp:
            p = self.execute(code, temp)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertFalse((Path(temp)/'credentials').exists())

    def test_dashboard_seed_and_mutating_endpoints_use_only_synthetic_data(self):
        with tempfile.TemporaryDirectory() as temp, socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
            listener.close()
            diagnostic = "import faulthandler, runpy; faulthandler.dump_traceback_later(10); runpy.run_module('clipmac.dev', run_name='__main__')"
            p = subprocess.Popen([sys.executable, '-c', diagnostic, '--data-dir', temp, '--port', str(port)],
                                 cwd=ROOT, env={**os.environ, 'CLIPMAC_DEV':'1'},
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                # Loopback tests must not be sent through a runner's system proxy.
                open_local = build_opener(ProxyHandler({})).open
                base = f'http://127.0.0.1:{port}'
                deadline = time.monotonic()+20
                while True:
                    try:
                        with open_local(base, timeout=2) as response: html = response.read().decode()
                        break
                    except (URLError, TimeoutError):
                        if p.poll() is not None or time.monotonic()>deadline:
                            if p.poll() is None:
                                p.terminate()
                            out, err = p.communicate(timeout=5)
                            self.fail(f'development server failed: {p.returncode}\n{out}\n{err}')
                        time.sleep(.05)
                self.assertIn('Alle Daten sind synthetisch', html)
                token = re.search(r"const token='([^']+)'", html).group(1)
                with open_local(base+'/api/state', timeout=3) as response: state = json.load(response)
                self.assertTrue(state['development'])
                with open_local(base+'/api/live/state', timeout=3) as response: live = json.load(response)
                self.assertTrue(live['development'])
                self.assertFalse(any(row['enabled'] for row in live['channels']))
                for endpoint in ('start','twitch','youtube-client','youtube-connect','tiktok/start','tiktok/connect','tiktok/check',
                                 'live/start','live/chat-credentials'):
                    request = Request(base+'/api/'+endpoint, data=b'{}', headers={'Content-Type':'application/json','X-ClipMac-Token':token})
                    with self.assertRaises(HTTPError) as ctx: open_local(request, timeout=3)
                    self.assertEqual(ctx.exception.code,400)
                    self.assertIn('Entwicklungsmodus',ctx.exception.read().decode())
                with open_local(base+'/api/learning/export', timeout=3) as response: data = json.load(response)
                self.assertFalse(data['model_trained'])
                self.assertFalse((Path(temp)/'credentials').exists())
            finally:
                if p.poll() is None:
                    p.send_signal(signal.SIGINT)
                try: p.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill(); p.communicate(timeout=5)
