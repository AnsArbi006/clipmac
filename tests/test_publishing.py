import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmac.engine import Engine
from clipmac.state import DEFAULTS, Store
from clipmac.publisher import UploadLimitReached, is_upload_limit_error


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "queue.db")
        self.engine = Engine(self.store)
        self.engine.active.set()
        for n in range(4):
            self.store.add({"id": f"test{n}", "title": "Test", "broadcaster_name": "Test"})
            self.store.update(f"test{n}", "ready", result={"metadata": {"title": "Test"}})
        self.cfg = {**DEFAULTS, "channel_id": "test-channel", "channel_title": "Testkanal"}
        self.patches = [patch("clipmac.engine.settings", return_value=self.cfg),
                        patch("clipmac.engine.RUNTIME", self.root),
                        patch("clipmac.engine.publisher.service_for_channel"),
                        patch("clipmac.engine.publisher.upload", return_value={"id": "testvideo01", "privacy": "public"})]
        self.mocks = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)

    def test_four_uploads_only_every_fifteen_minutes(self):
        self.cfg["publish_interval_minutes"] = 15
        for now, expected in [(1000,1), (1001,1), (1899,1), (1900,2), (2799,2), (2800,3), (3700,4)]:
            with patch("clipmac.engine.time.time", return_value=now):
                self.engine.publish_one()
            self.assertEqual(self.mocks[-1].call_count, expected)

    def test_zero_spacing_publishes_all_ready_without_waiting(self):
        self.cfg["publish_interval_minutes"] = 0
        with patch("clipmac.engine.time.time", return_value=1000):
            for _ in range(4):
                self.engine.publish_one()
        self.assertEqual(self.mocks[-1].call_count, 4)
        self.assertEqual(len(self.store.rows("published")), 4)

    def test_unknown_result_blocks_retry_and_following_jobs(self):
        self.mocks[-1].side_effect = TimeoutError("Antwort verloren")
        self.engine.publish_one()
        self.engine.publish_one()
        self.assertEqual(self.mocks[-1].call_count, 1)
        self.assertEqual(len(self.store.rows("upload_unknown")), 1)
        self.assertEqual(len(self.store.rows("ready")), 3)

    def test_explicit_limit_survives_restart_and_retries_after_24_hours(self):
        self.mocks[-1].side_effect = UploadLimitReached("Tageslimit")
        with patch("clipmac.engine.time.time", return_value=1000):
            self.engine.publish_one()
            self.engine.publish_one()
        self.assertEqual(self.mocks[-1].call_count, 1)
        self.assertEqual(len(self.store.rows("ready")), 4)
        self.assertEqual(len(self.store.rows("upload_unknown")), 0)
        reopened = Store(self.store.path)
        self.assertIsNone(reopened.ready_to_publish(87399, 0))
        self.assertIsNotNone(reopened.ready_to_publish(87400, 0))
        self.mocks[-1].side_effect = None
        with patch("clipmac.engine.time.time", return_value=87400):
            self.engine.publish_one()
        self.assertEqual(self.store.get("test0")["status"], "published")
        self.assertEqual(self.store.get("test0")["error"], "")

    def test_only_explicit_upload_limit_is_treated_as_rejection(self):
        from types import SimpleNamespace
        limit = SimpleNamespace(resp=SimpleNamespace(status=400), content=b'{"error":{"errors":[{"reason":"uploadLimitExceeded"}]}}')
        self.assertTrue(is_upload_limit_error(limit))
        limit.resp.status = 500
        self.assertFalse(is_upload_limit_error(limit))
        self.assertFalse(is_upload_limit_error(TimeoutError("Antwort verloren")))

    def test_project_daily_quota_is_rejected_without_unknown_upload(self):
        from clipmac.publisher import UploadProjectQuotaReached, is_upload_project_quota_error
        from types import SimpleNamespace
        exc = SimpleNamespace(resp=SimpleNamespace(status=429), content=b'{"error":{"message":"Quota exceeded: Video Uploads per day","errors":[{"reason":"rateLimitExceeded"}]}}')
        self.assertTrue(is_upload_project_quota_error(exc))
        exc.content = b'{"error":{"message":"Other rate limit","errors":[{"reason":"rateLimitExceeded"}]}}'
        self.assertFalse(is_upload_project_quota_error(exc))
        self.mocks[-1].side_effect = UploadProjectQuotaReached("Quota")
        self.engine.publish_one()
        self.engine.publish_one()
        self.assertEqual(self.mocks[-1].call_count, 1)
        self.assertEqual(len(self.store.rows("upload_unknown")), 0)
        self.assertEqual(len(self.store.rows("ready")), 4)

    def test_pause_and_missing_channel_prevent_upload(self):
        self.engine.pause()
        self.engine.publish_one()
        self.engine.active.set()
        self.cfg["channel_id"] = ""
        self.engine.publish_one()
        self.mocks[-1].assert_not_called()

    def test_youtube_private_response_not_claimed_public(self):
        self.mocks[-1].return_value = {"id": "testvideo01", "privacy": "private"}
        self.engine.publish_one()
        self.assertEqual(self.store.get("test0")["status"], "uploaded_private")
        self.assertEqual(self.store.get("test0")["youtube_id"], "testvideo01")

    def test_engine_obeys_persistent_pack_schedule(self):
        self.cfg.update(publish_batch_size=2, publish_batch_interval_minutes=60, streamers=['aaa', 'bbb'])
        for n in range(4):
            job = self.store.get(f'test{n}')
            job['clip']['streamer_login'] = 'aaa' if n < 2 else 'bbb'
            import json
            with self.store.db() as db:
                db.execute('UPDATE jobs SET clip=? WHERE id=?', (json.dumps(job['clip']), job['id']))
        for now, count in [(1000,1),(1001,2),(1002,2),(4600,2),(4601,3)]:
            with patch('clipmac.engine.time.time', return_value=now):
                self.engine.publish_one()
            self.assertEqual(self.mocks[-1].call_count, count)


if __name__ == "__main__":
    unittest.main()
