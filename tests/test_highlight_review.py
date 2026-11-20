import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmac.highlight_review import HighlightReviews, candidate_key, queued_highlight_rejection
from clipmac.state import DEFAULTS, Store


class HighlightReviewTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.runtime = Path(work.name).resolve()
        self.store = Store(self.runtime / "queue.sqlite")
        self.reviews = HighlightReviews(self.store, runtime=self.runtime)
        self.now = 1_800_000_000
        self.cfg = {**DEFAULTS, "streamers": ["test_channel"], "required_game_id": "42",
                    "required_game_name": "Testspiel", "publish_batch_size": 5}
        preview = self.runtime / "analysis" / "final.mp4"
        preview.parent.mkdir()
        preview.write_bytes(b"synthetische-vorschau")
        (preview.parent / "source.mp4").write_bytes(b"synthetischer-quellausschnitt")
        self.candidate = {"kind": "live", "source_id": "999", "channel": "test_channel", "start": 5, "end": 35,
                          "source_media_sha256": "a" * 64, "preview_ready": True, "render_revision": hashlib.sha256(preview.read_bytes()).hexdigest(),
                          "live_context": {"channel": "test_channel", "stream_id": "999", "category_id": "42",
                                           "start": self.now - 90, "end": self.now - 30, "category_review": False,
                                           "stream_started": self.now - 1000, "coverage": "exported", "vod_id": None},
                          "result": {"file": str(preview), "metadata": {"title": "Testhighlight", "description": "#Test", "tags": ["Test"]},
                                     "render": {"duration": 30}}, "model": "fixture", "prompt_version": 1}

    def test_candidate_key_includes_normalized_source_interval_and_media(self):
        equivalent = {**self.candidate, "start": 8, "end": 38,
                      "live_context": {**self.candidate["live_context"], "start": float(self.now - 93)}}
        self.assertEqual(candidate_key(self.candidate), candidate_key(equivalent))
        self.assertNotEqual(candidate_key(self.candidate), candidate_key({**self.candidate, "source_media_sha256": "b" * 64}))

    def test_score_and_feedback_are_versioned(self):
        self.reviews.score(self.candidate)
        self.reviews.score(self.candidate)
        self.reviews.score({**self.candidate, "prompt_version": 2})
        self.reviews.rate(self.candidate, "medium")
        self.reviews.rate(self.candidate, "good")
        self.reviews.report(self.candidate, "Testfehler am Ende", 29)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM highlight_scores_v1").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT count(*) FROM highlight_reviews_v1 WHERE kind='rating'").fetchone()[0], 2)
        snapshot = self.reviews.snapshot(self.candidate)
        self.assertEqual(snapshot["rating"], "good")
        self.assertEqual(snapshot["reports"][0]["position"], 29)
        revised = {**self.candidate, "render_revision": "b" * 64}
        self.assertEqual(self.reviews.snapshot(revised)["reports"], [])
        self.assertIsNone(self.reviews.snapshot(revised)["rating"])

    def test_explicit_live_approval_uses_native_package_and_canonical_copy(self):
        self.assertEqual(self.store.rows(), [])
        clip_id = self.reviews.promote(self.candidate, self.cfg, now=self.now)
        job = self.store.ready_to_publish(self.now, 0, self.cfg)
        output = self.runtime / "clips" / clip_id
        self.assertEqual(job["id"], clip_id)
        self.assertEqual(job["clip"]["vod_alignment"], "unknown")
        self.assertEqual(Path(job["result"]["file"]), output / "final.mp4")
        self.assertEqual((output / "source.mp4").read_bytes(), b"synthetischer-quellausschnitt")
        self.assertTrue((output / "highlight-approval.json").is_file())
        self.assertEqual(queued_highlight_rejection(job, self.store, self.cfg, runtime=self.runtime, now=self.now), "")
        with self.assertRaisesRegex(ValueError, "bereits bekannt"):
            self.reviews.promote(self.candidate, self.cfg, now=self.now)
        (output / "final.mp4").write_bytes(b"veraenderte-datei")
        self.assertIn("freigegebenen Fassung", queued_highlight_rejection(job, self.store, self.cfg, runtime=self.runtime, now=self.now))

    def test_open_report_is_a_hold_before_and_after_approval(self):
        report = self.reviews.report(self.candidate, "Testfehler im Bild")
        with self.assertRaisesRegex(ValueError, "offenen Fehlermeldungen"):
            self.reviews.promote(self.candidate, self.cfg, now=self.now)
        self.reviews.withdraw(self.candidate, report)
        clip_id = self.reviews.promote(self.candidate, self.cfg, now=self.now)
        report = self.reviews.report(self.candidate, "Testfehler nach Freigabe")
        self.assertFalse(self.store.transition(clip_id, "ready", "uploading"))
        self.reviews.withdraw(self.candidate, report)
        self.assertTrue(self.store.transition(clip_id, "ready", "uploading"))

    def test_overlap_with_known_and_deleted_twitch_clip_blocks_promotion(self):
        self.candidate["live_context"].update(vod_id="222", vod_offset=150)
        self.store.add({"id": "fixture-twitch-clip", "video_id": "222", "vod_offset": 148, "duration": 30})
        self.store.remove_confirmed_deleted("fixture-twitch-clip", "")
        with self.assertRaisesRegex(ValueError, "überlappender"):
            self.reviews.promote(self.candidate, self.cfg, now=self.now)

    def test_distinct_nonoverlapping_edits_from_one_recording_remain_independent(self):
        first = self.reviews.promote(self.candidate, self.cfg, now=self.now)
        second_preview = self.runtime / "another" / "final.mp4"
        second_preview.parent.mkdir()
        second_preview.write_bytes(b"zweite-synthetische-vorschau")
        other = {**self.candidate, "start": 37, "end": 58,
                 "result": {**self.candidate["result"], "file": str(second_preview)},
                 "render_revision": hashlib.sha256(second_preview.read_bytes()).hexdigest()}
        second = self.reviews.promote(other, self.cfg, now=self.now)
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.store.rows("ready")), 2)

    def test_overlap_discovered_after_approval_is_rechecked(self):
        self.candidate["live_context"].update(vod_id="222", vod_offset=150)
        key = self.reviews.promote(self.candidate, self.cfg, now=self.now)
        self.store.add({"id": "fixture-late-twitch-clip", "video_id": "222", "vod_offset": 154, "duration": 30})
        job = self.store.get(key)
        self.assertIn("überlappender", queued_highlight_rejection(job, self.store, self.cfg, runtime=self.runtime, now=self.now))

    def test_vod_nonmatching_category_stale_and_development_refused(self):
        with self.assertRaisesRegex(ValueError, "Nur Highlights"):
            self.reviews.promote({**self.candidate, "kind": "vod"}, self.cfg, now=self.now)
        with self.assertRaisesRegex(ValueError, "Spielkategorie"):
            self.reviews.promote(self.candidate, {**self.cfg, "required_game_id": "76"}, now=self.now)
        with self.assertRaisesRegex(ValueError, "Zeitfenster"):
            self.reviews.promote(self.candidate, self.cfg, now=self.now + 8 * 3600)
        with patch("clipmac.environment.DEVELOPMENT", True):
            with self.assertRaisesRegex(RuntimeError, "Entwicklungsmodus"):
                self.reviews.promote(self.candidate, self.cfg, now=self.now)
        self.assertEqual(self.store.rows(), [])
