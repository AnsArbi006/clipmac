import json
import tempfile
import unittest
from pathlib import Path

from clipmac.feedback import diagnose, original_time, prepare_case
from clipmac.state import DEFAULTS, Store


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "queue.sqlite")
        for name in ("clip1", "clip2"):
            self.store.add({"id": name, "broadcaster_name": "Streamer", "title": "Test"})
            self.store.update(name, "ready", result={"render": {"duration": 20}})

    def test_report_persists_and_blocks_only_reported_clip(self):
        report_id = self.store.add_report("clip1", "Facecam fehlt", 12.5, {**DEFAULTS, "client_secret": "not-in-report"})
        reopened = Store(self.store.path)
        self.assertEqual(reopened.report_rows()[0]["position"], 12.5)
        self.assertNotIn("not-in-report", json.dumps(reopened.report_rows()))
        self.assertEqual(reopened.ready_to_publish(100000, 0)["id"], "clip2")
        self.assertFalse(reopened.transition("clip1", "ready", "uploading"))
        reopened.withdraw_report(report_id)
        self.assertEqual(reopened.ready_to_publish(100000, 0)["id"], "clip1")

    def test_report_between_selection_and_claim_prevents_upload(self):
        selected = self.store.ready_to_publish(100000, 0)
        self.store.add_report(selected["id"], "Falscher Schnitt", None, DEFAULTS)
        self.assertFalse(self.store.transition(selected["id"], "ready", "uploading"))

    def test_published_video_is_not_changed_and_snapshot_is_immutable(self):
        self.store.update("clip1", "published", youtube_id="testvideo01", published=100)
        self.store.add_report("clip1", "Name falsch", None, DEFAULTS)
        self.assertEqual(self.store.get("clip1")["status"], "published")
        self.store.update("clip1", "published", result={})
        report = self.store.report_rows()[0]
        self.assertEqual(report["snapshot"]["result"]["render"]["duration"], 20)

    def test_validation(self):
        for note, pos in (("", None), ("x"*3001, None), ("Problem", -1), ("Problem", 21), ("Problem", float("nan")), ("Problem", "oops")):
            with self.assertRaises(ValueError):
                self.store.add_report("clip1", note, pos, DEFAULTS)
        with self.assertRaises(ValueError):
            self.store.add_report("missing", "Problem", None, DEFAULTS)
        self.assertEqual(self.store.report_rows(), [])

    def test_original_frame_mapping_across_removed_silence(self):
        spans = [[0, 2], [5, 8]]
        self.assertEqual(original_time(1.5, spans), 1.5)
        self.assertEqual(original_time(2, spans), 5)
        self.assertEqual(original_time(4, spans), 7)
        self.assertIsNone(original_time(7, spans))

    def test_camera_diagnosis_does_not_claim_visual_confirmation(self):
        result = {"render": {"timeline": [{"start": 0, "end": 20, "mode": "portrait", "face": None,
                  "layout": {"mode": "portrait", "content": {"w": 606}}}]}}
        analysis = diagnose("Kamera fehlt und Gameplay ist zu stark gezoomt", result, 5, 1920)
        self.assertEqual(analysis["category"], "camera")
        self.assertTrue(any("32 %" in f for f in analysis["facts"]))
        self.assertFalse(analysis["diagnosis_confirmed"])
        self.assertFalse(analysis["correction_applied"])

    def test_case_created_even_when_video_unavailable(self):
        self.store.add_report("clip1", "Kamera fehlt", None, DEFAULTS)
        report = self.store.report_rows()[0]
        analysis = prepare_case(report, self.root)
        case = json.loads((self.root / "feedback" / report["id"] / "case.json").read_text())
        self.assertEqual(case["regression"]["status"], "needs_review")
        self.assertIsNone(case["regression"]["expected_behavior"])
        self.assertTrue(analysis["evidence_notes"])
        self.store.report_evidence(report["id"], analysis)
        self.assertEqual(self.store.report_rows()[0]["evidence_state"], "ready")


if __name__ == "__main__":
    unittest.main()
