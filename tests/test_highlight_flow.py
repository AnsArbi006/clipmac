import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clipmac.highlight_review import HighlightReviews
from clipmac.highlight_web import HighlightDashboard
from clipmac.live import LiveHighlights
from clipmac.live_buffer import LiveBuffer
from clipmac.live_chat import SpikeDetector
from clipmac.long_highlights import LongHighlights, check_cancel
from clipmac.state import DEFAULTS, Store


def inspect_fixture(_):
    return {"format": {"duration": 60}, "streams": [{"codec_type": "audio"}, {"codec_type": "video"}]}


def transcript_fixture(*_):
    words = [(12, 12.4, "Aufpassen!"), (20, 20.4, "Kurve."),
             (29, 29.8, "Geschafft!"), (34, 34.5, "Sicher.")]
    return {"segments": [{"words": [{"start": a, "end": b, "word": text} for a, b, text in words]}]}


def model_fixture(units, _anchor, _cfg):
    return {"first": 0, "last": len(units) - 1, "criteria": {
        key: {"value": 2, "unit": index, "quote": units[index]["text"]}
        for index, key in enumerate(("hook", "context", "payoff"))}}


def ffmpeg_fixture(args, cancel, timeout):
    check_cancel(cancel)
    Path(args[-1]).write_bytes(b"synthetic-window")


def layout_fixture(group):
    return [{"index": index, "text": word["word"].upper(), "size": 84,
             "x": 500 + index * 70, "y": 1370, "width": 55} for index, word in enumerate(group)]


def render_fixture(window, folder, _cfg, _channel):
    (folder / "final.mp4").write_bytes(window.read_bytes() + b"-vertical-with-ass")
    return {"duration": 22.5, "width": 1080, "height": 1920}


class HighlightFlowTests(unittest.TestCase):
    def wait_for(self, worker, job_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = next(item for item in worker.snapshot()["jobs"] if item["id"] == job_id)
            if row["status"] in {"completed", "cancelled", "error"}:
                self.assertEqual(row["status"], "completed", row)
                return row
            time.sleep(.01)
        self.fail("Der synthetische Analyseauftrag blieb aktiv.")

    def test_simulated_recording_to_dashboard_with_explicit_queue_hold(self):
        cfg = {**DEFAULTS, "streamers": ["test_channel"], "required_game_id": "42",
               "required_game_name": "Testspiel", "publish_batch_size": 5}
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory).resolve()
            recorder = self.synthetic_recorder(runtime, cfg)
            self.addCleanup(recorder.close)
            capture, = recorder.snapshot(cfg)["candidates"]
            self.assertEqual(capture["coverage"], "complete")
            self.assertFalse(capture["category_review"])
            with patch("clipmac.long_highlights.media.binary", return_value="fake-ffmpeg"), \
                    patch("clipmac.long_highlights.cancellable_run", ffmpeg_fixture), \
                    patch("clipmac.long_highlights.media.run", return_value=SimpleNamespace(stdout="")), \
                    patch("clipmac.long_highlights.media.render_vertical", render_fixture), \
                    patch("clipmac.captions.layout", layout_fixture):
                worker = LongHighlights(runtime / "highlights", inspect=inspect_fixture, audio=lambda *_: None,
                                        transcribe=transcript_fixture, ask=model_fixture)
                self.addCleanup(worker.close)
                job = worker.start_live(capture, recorder.export, cfg)
                live_id, = self.wait_for(worker, job["id"])["candidates"]
                worker.close()
                self.assertEqual(recorder.snapshot(cfg)["candidates"][0]["coverage"], "exported")
                preview = worker.preview(live_id)
                self.assertIn("GESCHAFFT!", (preview.parent / "captions.ass").read_text(encoding="utf-8"))
                words = json.loads((preview.parent / "transcript.json").read_text(encoding="utf-8"))["segments"][0]["words"]
                self.assertEqual(words[0]["start"], 0)
                local_source = runtime / "local.mp4"
                local_source.write_bytes(b"synthetic-local-source")
                local_job = worker.start(local_source, "local", cfg)
                local_id, = self.wait_for(worker, local_job["id"])["candidates"]
                worker.close()

            store = Store(runtime / "queue.sqlite")
            dashboard = HighlightDashboard(worker, store)
            dashboard.reviews = HighlightReviews(store, runtime=runtime)
            rows = {row["id"]: row for row in dashboard.state(cfg)["candidates"]}
            self.assertEqual(rows[live_id]["score"]["mode"], "live")
            self.assertGreaterEqual(rows[live_id]["score"]["score"], 60)
            self.assertEqual(rows[local_id]["score"]["mode"], "text")
            self.assertTrue(rows[live_id]["can_promote"])
            self.assertFalse(rows[local_id]["can_promote"])
            self.assertEqual(store.rows(), [])
            with self.assertRaisesRegex(ValueError, "bestätigen"):
                dashboard.promote({"id": live_id}, cfg)
            report = dashboard.report({"id": live_id, "note": "Prüfe den Einstieg", "position": 1})
            with self.assertRaisesRegex(ValueError, "offenen Fehlermeldungen"):
                dashboard.promote({"id": live_id, "confirmed": True}, cfg)
            dashboard.withdraw({"id": live_id, "report_id": report})
            dashboard.rate({"id": live_id, "value": "good"})
            clip_id = dashboard.promote({"id": live_id, "confirmed": True}, cfg)
            self.assertEqual(store.get(clip_id)["status"], "ready")
            self.assertTrue((runtime / "clips" / clip_id / "captions.ass").is_file())
            entry = next(row for row in dashboard.state(cfg)["candidates"] if row["id"] == live_id)
            self.assertEqual(entry["review"]["rating"], "good")
            self.assertEqual(entry["review"]["promoted_clip_id"], clip_id)
            self.assertFalse(entry["can_promote"])

    def synthetic_recorder(self, runtime, cfg):
        start = time.time() - 250
        origin = {"stream_id": "1234567", "stream_started": start - 900,
                  "category_id": "42", "category_name": "Testspiel"}
        root = runtime / "ring"
        buffer = LiveBuffer(root)
        session, folder = buffer.begin("test_channel", origin, cfg, start)
        for i in range(48):
            name = f"{i:08d}.ts"
            (folder / name).write_bytes(b"synthetic-segment")
            buffer.add_segment(session, name, i * 5, i * 5 + 5, start + i * 5 + 5)
        buffer.observe_category(session, origin, start + 240)
        chat = SpikeDetector()
        chat.connect(start)
        for i in range(18):
            chat.message(start + i * 10 + 1, "listener-one")
            chat.message(start + i * 10 + 2, "listener-two")
            self.assertEqual(chat.tick(start + (i + 1) * 10), [])
        for i in range(20):
            chat.message(start + 181, f"listener-{i}")
        spike, = chat.tick(start + 190)
        buffer.trigger(session, spike, 6)

        def export(folder, segments, offset, duration, destination, cancel):
            check_cancel(cancel)
            self.assertEqual(len(segments), 13)
            self.assertAlmostEqual(offset, 4)
            self.assertAlmostEqual(duration, 60)
            destination.write_bytes(b"".join((folder / segment["name"]).read_bytes() for segment in segments))
            return destination

        return LiveHighlights(root, buffer=buffer, exporter=export)
