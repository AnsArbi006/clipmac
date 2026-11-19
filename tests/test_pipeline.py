import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from clipmac.state import Store, select_clips, overlaps, atomic_json
from clipmac.media import keep_intervals, silence_intervals, safe_ass, write_subtitles
from clipmac.publisher import upload_body


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "queue.db")
        self.now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)

    def clip(self, name, hours=1, views=10, offset=10):
        return {"id": name, "created_at": (self.now-timedelta(hours=hours)).isoformat(),
                "view_count": views, "video_id": "vod", "vod_offset": offset, "duration": 20}

    def test_window_and_views(self):
        clips = [self.clip("old", 8, 999), self.clip("future", -1, 999), self.clip("small", 1, 2, 100), self.clip("big", 2, 50)]
        selected = select_clips(clips, [], 3, self.now-timedelta(hours=7), self.now)
        self.assertEqual([c["id"] for c in selected], ["big", "small"])

    def test_id_and_vod_overlap(self):
        known = [self.clip("a")]
        chosen = select_clips([self.clip("a"), self.clip("b", offset=15), self.clip("c", offset=100)], known, 3,
                              self.now-timedelta(hours=7), self.now)
        self.assertEqual([c["id"] for c in chosen], ["c"])

    def test_missing_vod_not_false_duplicate(self):
        a, b = self.clip("a"), self.clip("b")
        a["video_id"] = b["video_id"] = ""
        self.assertFalse(overlaps(a, b))

    def test_dedup_survives_restart(self):
        self.assertTrue(self.store.add(self.clip("a")))
        reopened = Store(self.store.path)
        self.assertFalse(reopened.add(self.clip("a")))

    def test_spacing_across_batches_and_sleep(self):
        self.store.add(self.clip("a"))
        self.store.update("a", "published", published=1000)
        self.store.add(self.clip("b"))
        self.store.update("b", "ready")
        self.assertIsNone(self.store.ready_to_publish(1899, 15))
        self.assertEqual(self.store.ready_to_publish(1900, 15)["id"], "b")
        self.store.update("b", "published", published=90000)
        self.store.add(self.clip("c"))
        self.store.update("c", "ready")
        self.assertIsNone(self.store.ready_to_publish(90001, 15))
        self.assertEqual(self.store.ready_to_publish(90900, 15)["id"], "c")

    def test_crash_upload_is_not_retried(self):
        self.store.add(self.clip("a"))
        self.store.update("a", "uploading")
        self.store.add(self.clip("b"))
        self.store.update("b", "editing")
        self.store.recover()
        self.assertEqual(self.store.get("a")["status"], "upload_unknown")
        self.assertEqual(self.store.get("b")["status"], "queued")
        self.store.update("b", "ready")
        self.assertIsNone(self.store.ready_to_publish(999999, 15))

    def test_only_one_claim(self):
        self.store.add(self.clip("a"))
        self.assertTrue(self.store.transition("a", "queued", "downloading"))
        self.assertFalse(self.store.transition("a", "queued", "skipped"))

    def test_silence_preserves_edges(self):
        spans = keep_intervals([(2, 5)], 8, 0.15)
        self.assertEqual(spans, [(0, 2.15), (4.85, 8)])
        self.assertAlmostEqual(sum(b-a for a,b in spans), 5.3)

    def test_trailing_and_all_silence(self):
        self.assertEqual(silence_intervals("silence_start: 2.0\nsilence_end: 3.0\nsilence_start: 7.0", 10), [(2,3),(7,10)])
        with self.assertRaises(RuntimeError):
            keep_intervals([(0, 10)], 10)

    def test_caption_timing_and_escape(self):
        path = Path(self.temp.name) / "captions.ass"
        write_subtitles(path, {"segments": [{"words": [{"start": 1, "end": 1.4, "word": "Hallo"}, {"start": 1.5, "end": 2, "word": "Welt"}]}]})
        text = path.read_text()
        self.assertIn("0:00:01.00,0:00:01.50", text)
        self.assertIn("0:00:01.50,0:00:02.00", text)
        self.assertNotIn("\\", safe_ass("{\\pos(0,0)}"))

    def test_public_upload_metadata(self):
        body = upload_body({"title": "Titel", "description": "Quelle\n#Shorts", "tags": ["Shorts"]})
        self.assertEqual(body["status"]["privacyStatus"], "public")
        self.assertEqual(body["snippet"]["defaultLanguage"], "de")
        self.assertEqual(body["snippet"]["tags"], ["Shorts"])

    def test_private_credentials_permissions(self):
        path = Path(self.temp.name) / "secret.json"
        atomic_json(path, {"key": "test"}, private=True)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
