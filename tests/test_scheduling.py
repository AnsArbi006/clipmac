import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmac.state import DEFAULTS, Store
from clipmac.scheduling import batch_snapshot


class PackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'queue.db')
        self.cfg = {**DEFAULTS, 'streamers': ['aaa', 'bbb', 'ccc', 'ddd'],
                    'publish_batch_size': 5, 'publish_batch_interval_minutes': 60}
        for login in self.cfg['streamers']:
            for n in range(5):
                self.store.add({'id': f'{login}{n}', 'streamer_login': login, 'view_count': 100-n})
                self.store.update(f'{login}{n}', 'ready')

    def publish(self, now):
        j = self.store.ready_to_publish(now, 0, self.cfg)
        self.assertIsNotNone(j)
        with patch('clipmac.state.time.time', return_value=now):
            self.store.update(j['id'], 'published', published=now, youtube_id='video'+j['id'])
        return j['clip']['streamer_login']

    def test_five_then_hour_from_last_upload_and_rotating_extra(self):
        self.assertEqual([self.publish(1000+n) for n in range(5)], ['aaa','bbb','ccc','ddd','aaa'])
        self.store = Store(self.store.path)
        self.assertIsNone(self.store.ready_to_publish(4603, 0, self.cfg))
        self.assertEqual([self.publish(4604+n) for n in range(5)], ['bbb','ccc','ddd','aaa','bbb'])
        self.assertEqual(batch_snapshot(self.store, self.cfg)['next_batch_at'], 8208)

    def test_slow_streamer_keeps_its_place_and_report_blocks_it(self):
        self.store.update('bbb0', 'editing')
        self.assertEqual(self.publish(1000), 'aaa')
        self.assertIsNone(self.store.ready_to_publish(1001, 0, self.cfg))
        self.store.update('bbb0', 'ready')
        report = self.store.add_report('bbb0', 'Die Kamera fehlt', None, self.cfg)
        self.assertIsNone(self.store.ready_to_publish(1002, 0, self.cfg))
        self.store.withdraw_report(report)
        self.assertEqual(self.publish(1003), 'bbb')

    def test_unknown_or_quota_blocks_remaining_pack(self):
        self.publish(1000)
        j = self.store.ready_to_publish(1001, 0, self.cfg)
        self.store.update(j['id'], 'upload_unknown')
        self.assertIsNone(self.store.ready_to_publish(90000, 0, self.cfg))
        self.store.update(j['id'], 'ready')
        self.store.defer_uploads(100000)
        self.assertIsNone(self.store.ready_to_publish(99999, 0, self.cfg))

    def test_initial_activation_respects_previous_uploads(self):
        self.store.update('aaa0', 'published', published=1000)
        self.assertIsNone(self.store.ready_to_publish(4599, 0, self.cfg))
        self.assertIsNotNone(self.store.ready_to_publish(4600, 0, self.cfg))

    def test_only_available_streamers_and_partial_pack_still_waits(self):
        for j in self.store.rows():
            if j['id'] not in ('aaa0', 'ddd0', 'ddd1'):
                self.store.update(j['id'], 'policy_blocked')
        self.assertEqual([self.publish(1000+n) for n in range(3)], ['aaa','ddd','ddd'])
        self.assertIsNone(self.store.ready_to_publish(2000, 0, self.cfg))

    def test_deleted_clip_removed_from_gallery_but_never_readded(self):
        clip = self.store.get('aaa0')['clip']
        self.store.update('aaa0', 'published', youtube_id='videoaaa0')
        self.store.add_report('aaa0', 'Falscher Ausschnitt', None, self.cfg)
        self.store.record_performance(self.store.get('aaa0'), {'views': 3, 'availability': 'public', 'youtube_metadata': {'title': 'Test'}}, 2000, 1000)
        with self.assertRaises(ValueError):
            self.store.remove_confirmed_deleted('aaa0', 'wrong')
        self.store.remove_confirmed_deleted('aaa0', 'videoaaa0')
        self.assertIsNone(self.store.get('aaa0'))
        self.assertFalse(self.store.add(clip))
        self.assertIn(clip, self.store.known_clips())
        self.assertEqual(self.store.report_rows(), [])
        self.assertEqual(self.store.performance_rows(), [])
        self.assertEqual(self.store.youtube_metadata_rows(), [])


if __name__ == '__main__':
    unittest.main()
