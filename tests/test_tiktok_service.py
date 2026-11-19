import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from clipmac.state import atomic_json
from clipmac.tiktok_service import TikTokController, recover_before_post


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / 'final.mp4'
        self.video.write_bytes(b'test')
        policy_patch = patch("clipmac.state.settings", return_value={})
        policy_patch.start()
        self.addCleanup(policy_patch.stop)
        self.store = MagicMock()
        self.store.rows.return_value = [{'id':'clip1','status':'ready','result':{'file':str(self.video),'metadata':{'title':'Clip'}},'clip':{}}]
        self.store.report_rows.return_value = []
        self.store.rating_rows.return_value = []
        atomic_json(self.root / 'account.json', {'account':'demo.clips'})
        self.controller = TikTokController(self.store, self.root, [sys.executable, '-m', 'fake_worker'])

    def receipt(self, status, stage):
        p = self.root / 'demo.clips/clip1.json'
        atomic_json(p, {'status':status,'stage':stage})
        return p

    def test_start_is_single_flight_and_stop_does_not_kill_upload(self):
        process = MagicMock(); process.poll.return_value = None
        with patch('clipmac.tiktok_service.subprocess.Popen', return_value=process) as spawn:
            self.controller.start()
            with self.assertRaises(ValueError): self.controller.start()
            self.assertEqual(spawn.call_count,1)
            self.controller.stop()
            self.assertTrue(self.controller.stop_file.exists())
            self.assertEqual(self.controller.snapshot()['phase'],'stopping')
            process.kill.assert_not_called(); process.terminate.assert_not_called()

    def test_stop_before_worker_start_remains_requested(self):
        process=MagicMock();process.poll.return_value=None
        with patch('clipmac.tiktok_service.subprocess.Popen',return_value=process):
            self.controller.start()
            self.controller.stop()
            self.assertTrue(self.controller.stop_file.exists())

    def test_only_pre_submission_record_is_recoverable(self):
        p=self.receipt('upload_unknown','preparing_form')
        recover_before_post(self.root,'demo.clips')
        self.assertEqual(json.loads(p.read_text())['status'],'cancelled_before_post')
        p=self.receipt('upload_unknown','submit_started')
        recover_before_post(self.root,'demo.clips')
        self.assertEqual(json.loads(p.read_text())['status'],'upload_unknown')
        with patch('clipmac.tiktok_service.subprocess.Popen') as spawn:
            with self.assertRaises(ValueError): self.controller.start()
            spawn.assert_not_called()

    def test_snapshot_preserves_review_vs_public_and_sanitizes_url(self):
        p=self.receipt('pending_review','submit_started')
        d=json.loads(p.read_text());d['video_url']='javascript:alert(1)';d['secret']='must never be returned';atomic_json(p,d)
        state=self.controller.snapshot()
        self.assertEqual(state['pending_review'],1);self.assertEqual(state['public'],0)
        self.assertEqual(state['ready'],0);self.assertEqual(state['recent'][0]['url'],'')
        self.assertNotIn('secret',json.dumps(state))

    def test_finished_process_is_not_reported_as_running(self):
        atomic_json(self.controller.state_file,{'phase':'uploading'})
        state=self.controller.snapshot()
        self.assertEqual(state['phase'],'interrupted');self.assertFalse(state['running'])

    def test_reported_or_bad_rated_clip_is_not_ready(self):
        self.store.report_rows.return_value=[{'clip_id':'clip1','status':'open'}]
        self.assertEqual(self.controller.snapshot()['ready'],0)
        self.store.report_rows.return_value=[]
        self.store.rating_rows.return_value=[{'clip_id':'clip1','value':'bad'}]
        self.assertEqual(self.controller.snapshot()['ready'],0)

    def test_category_filter_excludes_legacy_published_clips(self):
        with patch('clipmac.state.settings', return_value={'required_game_id':'1867279146'}):
            self.assertEqual(self.controller.snapshot()['ready'], 0)

    def test_hourly_wait_is_stoppable_and_does_not_open_browser(self):
        with patch('clipmac.state.settings',return_value={'publish_batch_size':5}), \
                patch('clipmac.tiktok_schedule.next_pack',return_value={'ids':[],'next_at':9999999999,'blocked':False}), \
                patch('clipmac.tiktok_service.subprocess.Popen') as spawn:
            self.controller.start()
            self.assertTrue(self.controller.auto_enabled())
            self.assertEqual(self.controller.snapshot()['phase'],'waiting')
            self.assertFalse(self.controller.snapshot()['can_start'])
            spawn.assert_not_called()
            self.controller.stop()
            self.assertFalse(self.controller.auto_enabled())

    def test_auto_loop_stops_on_error_without_retrying_upload(self):
        self.controller._set_auto(True)
        atomic_json(self.controller.state_file,{'phase':'error'})
        self.controller.shutdown=MagicMock()
        self.controller.shutdown.wait.side_effect=[False,True]
        with patch('clipmac.tiktok_service.subprocess.Popen') as spawn:
            self.controller._auto_loop()
        self.assertFalse(self.controller.auto_enabled())
        spawn.assert_not_called()
