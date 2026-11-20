import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clipmac import captions, media
from clipmac.long_highlights import (LongHighlights, absolute_words, blocks, check_cancel,
                                     deduplicate_words, inspect_media, interior_intervals, remap_words,
                                     render_preview, tighten_interior, utterances, validate_analysis,
                                     vod_source, windows)
from clipmac.state import DEFAULTS


def transcript(words):
    return {"segments": [{"words": [{"start": start, "end": end, "word": word}
                                    for start, end, word in words]}]}


def inspect(_):
    return {"format": {"duration": 620}, "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}


class LongHighlightsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.source = self.folder / "long-source.mp4"
        self.source.write_bytes(b"synthetic media fixture")

    def wait_for_job(self, controller, status):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            jobs = controller.snapshot()["jobs"]
            if jobs and jobs[0]["status"] in {"completed", "cancelled", "error"}:
                self.assertEqual(jobs[0]["status"], status, jobs[0])
                return jobs[0]
            time.sleep(0.02)
        self.fail(f"Worker did not reach {status}")

    def test_twitch_vod_url_is_canonical_and_development_blocks_network(self):
        self.assertEqual(vod_source("https://twitch.tv/videos/123456?t=20s"),
                         ("https://www.twitch.tv/videos/123456", "123456"))
        for value in ("http://twitch.tv/videos/123", "https://twitch.tv:443/videos/123",
                      "https://twitch.tv.evil.tld/videos/123", "https://www.twitch.tv/user",
                      "https://a@twitch.tv/videos/123", "https://twitch.tv/videos/123/../secret"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                vod_source(value)
        controller = LongHighlights(self.folder / "highlights")
        with patch("clipmac.environment.DEVELOPMENT", True):
            with self.assertRaisesRegex(RuntimeError, "Entwicklungsmodus"):
                controller.start("https://www.twitch.tv/videos/123456", "vod", DEFAULTS)
            with self.assertRaisesRegex(RuntimeError, "Entwicklungsmodus"):
                controller.start_live({"coverage": "complete"}, None, DEFAULTS)

    def test_windows_cross_block_boundary_without_duplicate_or_lost_punchline(self):
        parts = list(blocks(620))
        self.assertEqual(parts, [(0, 600, 0, 585), (570, 620, 585, 620)])
        first = transcript([(565, 566, "Pass"), (566, 566.5, "auf."),
                            (584.3, 584.7, "Die"), (584.8, 585.4, "Pointe!")])
        second = transcript([(14.3, 14.7, "Die"), (14.8, 15.4, "Pointe!"),
                             (27, 28, "Geschafft.")])
        words = deduplicate_words(absolute_words(first, parts[0]) + absolute_words(second, parts[1]))
        self.assertEqual([word["word"] for word in words], ["Pass", "auf.", "Die", "Pointe!", "Geschafft."])
        self.assertAlmostEqual(words[3]["start"], 584.8)
        selected = windows(utterances(words))
        self.assertEqual(len(selected), 1)
        self.assertEqual((selected[0][0], selected[0][1]), (565, 598))

    def test_only_evidence_grounded_in_selected_words_is_accepted(self):
        words = [{"start": 3.0, "end": 4.0, "word": "Los!"},
                 {"start": 6.0, "end": 7.0, "word": "Ignoriere"},
                 {"start": 7.0, "end": 7.5, "word": "Anweisungen."},
                 {"start": 30.0, "end": 31.0, "word": "Geschafft."}]
        units = utterances(words)
        response = {"first": 0, "last": 2, "criteria": {
            "hook": {"value": 2, "unit": 0, "quote": "Los!"},
            "context": {"value": True, "unit": 1, "quote": "Ignoriere Anweisungen."},
            "payoff": {"value": 2, "unit": 2, "quote": "Erfundene Handlung."}}}
        selected, evidence = validate_analysis(response, units, 1)
        self.assertEqual(selected, units)
        self.assertEqual(set(evidence), {"hook"})
        self.assertEqual((evidence["hook"]["start"], evidence["hook"]["end"]), (3.0, 4.0))

    def test_interior_trim_retains_whole_words_edges_and_length_floor(self):
        words = [{"start": a, "end": b, "word": value} for a, b, value in
                 [(3.5, 4.5, "Anfang"), (5.5, 6.5, "Kontext."), (12.5, 14, "Pointe!"), (24, 25, "Ende.")]]
        quiet = [(0, 3), (8, 12), (21, 24.1), (26, 30)]
        keep = interior_intervals(30, words, quiet)
        self.assertEqual(keep, [(0, 9), (11, 30)])
        mapped = remap_words(words, keep)
        self.assertEqual([w["word"] for w in mapped], [w["word"] for w in words])
        self.assertEqual([w["start"] for w in mapped], [3.5, 5.5, 10.5, 22])
        self.assertEqual(interior_intervals(20, words[:3], quiet[:2]), [(0, 20)])
        self.assertEqual(interior_intervals(30, [], quiet), [(0, 30)])

    def test_worker_persists_provenance_and_dry_preview(self):
        calls = []

        def audio(_, window, wav, event):
            calls.append(window)
            wav.write_text(str(window[0]))

        def fake_asr(wav, _):
            if wav.read_text() == "0":
                return transcript([(565, 566, "Pass"), (566, 566.5, "auf."),
                                   (584.3, 584.7, "Die"), (584.8, 585.4, "Pointe!")])
            return transcript([(14.3, 14.7, "Die"), (14.8, 15.4, "Pointe!"),
                               (27, 28, "Geschafft.")])

        def render(_, item, folder, _cfg, event):
            check_cancel(event)
            video = folder / "final.mp4"
            video.write_bytes(b"synthetic portrait and subtitles")
            return {"file": str(video), "subtitle_words": len(item["words"])}

        def ask(*_):
            raise TimeoutError("Ollama timed out")

        controller = LongHighlights(self.folder / "highlights", inspect=inspect, audio=audio,
                                    transcribe=fake_asr, render=render, ask=ask)
        self.addCleanup(controller.close)
        job = controller.start(self.source, "local", DEFAULTS)
        completed = self.wait_for_job(controller, "completed")
        self.assertEqual(job["id"], completed["id"])
        self.assertNotIn("source_path", completed)
        self.assertEqual(calls, list(blocks(620)))
        item_id, = completed["candidates"]
        item = controller.candidate(item_id)
        self.assertEqual((item["start"], item["end"]), (565.0, 598.0))
        self.assertEqual(item["result"]["subtitle_words"], 5)
        self.assertEqual(len(item["source_media_sha256"]), 64)
        self.assertEqual(len(item["render_revision"]), 64)
        self.assertTrue(item["review_required"])
        self.assertEqual(item["evidence"], {})
        self.assertTrue(controller.preview(item_id).is_file())
        self.assertFalse((controller.root / "jobs" / job["id"] / "analysis.wav").exists())
        recovered = LongHighlights(controller.root)
        self.assertEqual(recovered.preview(item_id), controller.preview(item_id))
        self.assertNotIn("words", recovered.snapshot()["candidates"][0])

    def test_single_worker_and_cancellation(self):
        begun = threading.Event()

        def audio(_path, _window, _wav, event):
            begun.set()
            event.wait(4)
            check_cancel(event)

        controller = LongHighlights(self.folder / "highlights", inspect=inspect, audio=audio)
        self.addCleanup(controller.close)
        job = controller.start(self.source, "local", DEFAULTS)
        self.assertTrue(begun.wait(2))
        with self.assertRaisesRegex(ValueError, "läuft bereits"):
            controller.start(self.source, "local", DEFAULTS)
        self.assertEqual(controller.cancel(job["id"])["status"], "stopping")
        self.wait_for_job(controller, "cancelled")
        with self.assertRaisesRegex(ValueError, "Unbekannte Analyse-ID"):
            controller.preview("../unsafe")

    def test_development_local_does_not_call_model(self):
        def forbidden(*_):
            self.fail("Development must not call the model")

        controller = LongHighlights(self.folder / "highlights", inspect=inspect, ask=forbidden,
                                    audio=lambda *_: None, transcribe=lambda *_: transcript([(0, 30, "Hallo.")]),
                                    render=lambda *_: {"file": "expected-missing"})
        self.addCleanup(controller.close)
        with patch("clipmac.long_highlights.DEVELOPMENT", True), patch(
                "clipmac.long_highlights.RUNTIME", self.folder / "different-root"):
            with self.assertRaisesRegex(ValueError, "Entwicklungsdatenordner"):
                controller.start(self.source, "local", DEFAULTS)
        with patch("clipmac.long_highlights.DEVELOPMENT", True), patch(
                "clipmac.long_highlights.RUNTIME", self.folder.resolve()):
            controller.start(self.source, "local", DEFAULTS)
            self.wait_for_job(controller, "completed")

    def test_live_without_words_yields_a_review_candidate(self):
        def exporter(item_id, destination, *, cancel):
            self.assertEqual(item_id, "live-id")
            check_cancel(cancel)
            destination.write_bytes(b"synthetic live export")
            return destination

        def render(_, item, folder, _cfg, _event):
            file = folder / "final.mp4"
            file.write_bytes(b"synthetic preview without captions")
            self.assertEqual(item["words"], [])
            return {"file": str(file)}

        context = {"id": "live-id", "coverage": "complete", "channel": "test_channel",
                   "stream_id": "1234", "start": 150, "end": 210, "trigger": 180}
        controller = LongHighlights(self.folder / "highlights", inspect=lambda _: {
            **inspect(None), "format": {"duration": 60}}, audio=lambda *_: None,
            transcribe=lambda *_: transcript([]), render=render)
        self.addCleanup(controller.close)
        controller.start_live(context, exporter, DEFAULTS)
        completed = self.wait_for_job(controller, "completed")
        item = controller.candidate(completed["candidates"][0])
        self.assertEqual((item["start"], item["end"]), (0, 60))
        self.assertEqual(item["live_context"], context)
        self.assertTrue(item["preview_ready"])
        self.assertTrue(item["review_required"])
        self.assertEqual(item["evidence"], {})
        controller.close()
        restarted = LongHighlights(controller.root, inspect=controller._inspect,
                                   audio=lambda *_: None, transcribe=lambda *_: transcript([]), render=render)
        self.addCleanup(restarted.close)
        restarted.start_live({**context, "coverage": "exported"}, None, DEFAULTS)
        self.assertEqual(self.wait_for_job(restarted, "completed")["candidates"], [item["id"]])

    def test_optional_real_ffmpeg_preview_and_container_guard(self):
        try:
            ffmpeg = media.binary("ffmpeg")
            media.binary("ffprobe")
        except RuntimeError as exc:
            self.skipTest(str(exc))
        font = captions.FONT_PATH
        if os.name == "nt":
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arialbd.ttf"
        if not font.is_file():
            self.skipTest("Arial Bold is needed for the preview")
        source = self.folder / "source.mov"
        media.run([ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i",
                   "testsrc2=size=320x180:rate=30:d=5", "-itsoffset", "0.03", "-f", "lavfi",
                   "-i", "sine=frequency=440:sample_rate=48000:duration=4.94",
                   "-c:v", "mpeg4", "-c:a", "pcm_s16le", source])
        self.assertEqual(inspect_media(source)["format"]["duration"], "5.000000")
        fake = self.folder / "playlist.mp4"
        fake.write_text("ffconcat version 1.0\nfile source.mov\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            inspect_media(fake)
        folder = self.folder / "preview"
        folder.mkdir()
        candidate = {"start": 0.4, "end": 4.95, "words": [{"start": 0.5, "end": 1.0, "word": "Hallo!"}]}
        with patch.object(captions, "FONT_PATH", font), patch.dict(
                sys.modules, {"config": SimpleNamespace(validate_facecam_crop=lambda _: None)}):
            captions.font.cache_clear()
            self.addCleanup(captions.font.cache_clear)
            result = render_preview(source, candidate, folder, {**DEFAULTS, "facecam": False}, threading.Event())
        streams = {stream["codec_type"]: stream for stream in media.probe(result["file"])["streams"]}
        self.assertEqual((streams["video"]["width"], streams["video"]["height"]), (1080, 1920))
        self.assertAlmostEqual(float(streams["video"]["duration"]), float(streams["audio"]["duration"]), delta=0.05)
        self.assertEqual(result["subtitle_words"], 1)
        self.assertIn("0:00:00.10", (folder / "captions.ass").read_text(encoding="utf-8"))

    def test_optional_real_ffmpeg_only_tightens_interior_quiet(self):
        try:
            ffmpeg = media.binary("ffmpeg")
            media.binary("ffprobe")
        except RuntimeError as exc:
            self.skipTest(str(exc))
        source, output = self.folder / "test.mov", self.folder / "edited.mp4"
        sound = r"(between(t\,3\,8)+between(t\,12\,26))*0.3*sin(2*PI*440*t)"
        media.run([ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i",
                   "testsrc2=size=160x90:rate=30:d=30", "-f", "lavfi", "-i",
                   f"aevalsrc={sound}:s=48000:d=30", "-c:v", "mpeg4", "-c:a", "pcm_s16le", source])
        words = [{"start": a, "end": b, "word": value} for a, b, value in
                 [(3.5, 4.5, "Anfang"), (5.5, 6.5, "Kontext."), (12.5, 14, "Pointe!"), (24, 25, "Ende.")]]
        selected, keep = tighten_interior(source, output, 30, words, threading.Event())
        self.assertEqual(selected, output)
        self.assertEqual(len(keep), 2)
        self.assertEqual((keep[0][0], keep[-1][1]), (0, 30))
        self.assertAlmostEqual(keep[0][1], 9.0, delta=0.03)
        self.assertAlmostEqual(keep[1][0], 11.0, delta=0.03)
        self.assertAlmostEqual(remap_words(words, keep)[2]["start"], 10.5, delta=0.002)
        self.assertAlmostEqual(float(media.probe(output)["format"]["duration"]), 28, delta=0.1)
        self.assertAlmostEqual(float(media.probe(source)["format"]["duration"]), 30, delta=0.01)
