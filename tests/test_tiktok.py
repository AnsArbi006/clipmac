import contextlib
import json
import importlib.metadata
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from clipmac import tiktok


try:
    importlib.metadata.version("tiktok-uploader")
    HAS_UPLOADER = True
except importlib.metadata.PackageNotFoundError:
    HAS_UPLOADER = False


@unittest.skipUnless(HAS_UPLOADER, "TikTok-Tests benötigen .venv-tiktok")
class TikTokPilotTests(unittest.TestCase):
    def enterContext(self, context):
        value = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return value

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.enterContext(patch.object(tiktok, "RECEIPTS", self.root))
        self.enterContext(patch.object(tiktok, "clip_payload", return_value={
            "clip_id": "clip1", "file": "/test/final.mp4", "caption": "#Twitch", "sha256": "abc"}))
        self.page = MagicMock()
        @contextlib.contextmanager
        def browser():
            yield None, self.page
        self.enterContext(patch.object(tiktok, "browser", browser))
        self.identity = self.enterContext(patch.object(tiktok, "own_account", return_value="demo.clips"))
        self.upload = self.enterContext(patch("tiktok_uploader.upload.complete_upload_form"))

    def read(self):
        return json.loads(tiktok.receipt_path("demo.clips", "clip1").read_text())

    def test_wrong_account_blocks_before_upload(self):
        self.identity.return_value = "other.account"
        with self.assertRaises(ValueError):
            tiktok.publish("demo.clips", "clip1")
        self.upload.assert_not_called()
        self.assertFalse(tiktok.receipt_path("demo.clips", "clip1").exists())

    def test_timeout_marks_unknown_and_blocks_retry(self):
        self.upload.side_effect = TimeoutError("sensitive vendor error")
        with self.assertRaisesRegex(RuntimeError, "unklar"):
            tiktok.publish("demo.clips", "clip1")
        self.assertEqual(self.read()["status"], "upload_unknown")
        self.assertNotIn("sensitive", json.dumps(self.read()))
        with self.assertRaises(ValueError):
            tiktok.publish("demo.clips", "clip1")
        self.assertEqual(self.upload.call_count, 1)

    def test_confirmation_is_not_claimed_as_verified(self):
        tiktok.publish("demo.clips", "clip1")
        self.assertEqual(self.read()["status"], "confirmation_received")
        self.assertNotIn("video_url", self.read())

    def test_verify_rejects_other_account_url(self):
        tiktok.publish("demo.clips", "clip1")
        with self.assertRaises(ValueError):
            tiktok.verify("demo.clips", "clip1", "https://www.tiktok.com/@other/video/123")
        self.assertEqual(self.read()["status"], "confirmation_received")

    def test_verified_receipt_keeps_clip_identity(self):
        tiktok.publish("demo.clips", "clip1")
        tiktok.verify("demo.clips", "clip1", "https://www.tiktok.com/@demo.clips/video/123")
        self.assertEqual(self.read()["status"], "verified")
        self.assertEqual(self.read()["sha256"], "abc")

    def test_account_rejects_paths(self):
        for account in ("../../profile", "https://tiktok.com", "a/b"):
            with self.assertRaises(ValueError):
                tiktok.account_name(account)

    def test_stop_before_post_never_clicks_and_is_safe_to_resume(self):
        import tiktok_uploader.upload as upload
        self.upload.side_effect=lambda *a, **kw: upload._post_video(self.page)
        checks=iter([False,False,True])
        with self.assertRaises(tiktok.StopRequested):
            tiktok.publish('demo.clips','clip1',should_stop=lambda: next(checks))
        self.assertEqual(self.read()['status'],'cancelled_before_post')
        self.page.locator.return_value.click.assert_not_called()

    def test_stop_before_upload_does_not_open_browser(self):
        with patch.object(tiktok,'browser') as browser:
            with self.assertRaises(tiktok.StopRequested):
                tiktok.publish('demo.clips','clip1',should_stop=lambda: True)
            browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
