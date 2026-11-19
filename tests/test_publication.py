import unittest
from scripts.check_publication import issues


class PublicationTests(unittest.TestCase):
    def test_blocks_private_paths_and_media(self):
        for path in ('runtime/settings.json', '.venv/bin/python', 'credentials/account.json', 'clip.mp4', 'queue.sqlite'):
            self.assertTrue(issues(path, ''), path)

    def test_flags_secret_without_echoing_value(self):
        value = 'ghp_' + 'a' * 30
        found = issues('source.py', value)
        self.assertEqual(found, ['sensitive pattern'])
        self.assertNotIn(value, str(found))
        self.assertTrue(issues('source.py', '{"refresh_token": "' + 'x'*30 + '"}'))

    def test_accepts_source_and_placeholder(self):
        self.assertEqual(issues('clipmac/example.py', 'client_secret = ""'), [])
        self.assertEqual(issues('examples/settings.gta6.json', '{"channel_id":""}'), [])
