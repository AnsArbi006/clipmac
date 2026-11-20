"""CM-012 B: long-source blocks, word remapping, FFmpeg cut/render checks and dashboard server."""

import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from clipmac_windows import analysis_core as core

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


class CoreTests(unittest.TestCase):
    def test_blocks_overlap_and_cover(self):
        windows = list(core.blocks(1500))
        self.assertEqual([w[:2] for w in windows], [(0, 600), (570, 1170), (1140, 1500)])
        # usable halves tile the timeline without gaps
        self.assertEqual(windows[0][3], windows[1][2])

    def test_highlight_at_block_boundary_deduplicated(self):
        # Same spoken word reported by both overlapping blocks near 585 s.
        a = core.absolute_words({"segments": [{"words": [{"start": 584.0, "end": 584.6, "word": "Wahnsinn!"}]}]},
                                (0, 600, 0, 585))
        b = core.absolute_words({"segments": [{"words": [{"start": 14.1, "end": 14.6, "word": "Wahnsinn!"}]}]},
                                (570, 1170, 585, 1155))
        words = core.deduplicate_words(a + b + [{"start": 584.1, "end": 584.6, "word": "wahnsinn"}])
        self.assertEqual(len(words), 1)

    def test_sentence_boundaries_kept(self):
        words = [{"start": i * 0.5, "end": i * 0.5 + 0.4, "word": w}
                 for i, w in enumerate("Wir fahren los. Was ist das? Unglaublich!".split())]
        units = core.utterances(words)
        self.assertEqual([u["text"] for u in units], ["Wir fahren los.", "Was ist das?", "Unglaublich!"])

    def test_remap_after_trim(self):
        words = [{"start": 1.0, "end": 1.5, "word": "a"}, {"start": 10.0, "end": 10.5, "word": "b"}]
        out = core.remap_words(words, [(0, 5), (8, 12)])
        self.assertEqual(out[1], {"start": 7.0, "end": 7.5, "word": "b"})
        with self.assertRaises(ValueError):
            core.remap_words([{"start": 4.5, "end": 5.5, "word": "x"}], [(0, 5), (8, 12)])

    def test_invalid_model_answer_ignored(self):
        units = core.utterances([{"start": i, "end": i + 0.5, "word": f"w{i}."} for i in range(60)])
        _, evidence = core.validate_analysis({"first": 0, "last": 59, "criteria": {
            "hook": {"value": 2, "unit": 0, "quote": "erfunden"}}}, units, 10)
        self.assertEqual(evidence, {})  # quote not in transcript, span > 120 s

    def test_quote_across_sentences_with_wrong_unit_is_verified(self):
        text = "Wir fahren los. Was ist das? Das gibt es nicht!".split()
        units = core.utterances([{"start": i * 2.5, "end": i * 2.5 + 2.4, "word": w} for i, w in enumerate(text)])
        _, evidence = core.validate_analysis({"first": 0, "last": 2, "criteria": {
            "payoff": {"value": 2, "unit": 0, "quote": "was ist das das gibt es nicht und erfunden"},
            "hook": {"value": 2, "unit": 0, "quote": "komplett erfunden hier"}}}, units, 1)
        self.assertEqual(evidence["payoff"]["quote"], "Was ist das? Das gibt es nicht!")
        self.assertNotIn("hook", evidence)


@unittest.skipUnless(FFMPEG, "FFmpeg fehlt")
class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, video=70, audio=70, name="source.mp4"):
        path = self.dir / name
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={video}",
                        "-f", "lavfi", "-i", f"sine=frequency=300:duration={audio}",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", path],
                       check=True)
        return path

    def process(self, quality, source=None):
        from clipmac_windows import pipeline, synthetic
        cand = {"id": "a" * 32, "channel": "papaplatte", "start": 0, "end": 70, "trigger": 35,
                "category_review": False, "category_pending": False,
                "chat": {"messages": 45, "baseline_messages": 5, "participants": 25, "baseline_participants": 5}}
        ask = synthetic.fake_ask_factory(lambda c: quality)
        out = self.dir / quality
        out.mkdir()
        return pipeline.process(cand, source or self.source(), out, {"score_threshold": 70, "ollama_model": "x"},
                                transcribe=synthetic.fake_transcribe, ask=lambda u, a, c: ask(u, a, c),
                                cancel=threading.Event()), out

    def test_good_clip_rendered_checked_eligible(self):
        result, out = self.process("good")
        self.assertTrue(result["eligible"], result["decision"])
        self.assertTrue(20 <= result["duration"] <= 120)
        for name in ("final.mp4", "original.mp4", "thumb.jpg", "result.json"):
            self.assertTrue((out / name).is_file(), name)
        self.assertEqual(json.loads((out / "result.json").read_text(encoding="utf-8"))["decision"]["version"],
                         "cm012-windows-score-v1")

    def test_weak_and_broken_model_not_eligible(self):
        source = self.source()
        weak, _ = self.process("weak", source)
        broken, _ = self.process("broken", source)
        self.assertFalse(weak["eligible"])
        self.assertFalse(broken["eligible"])
        self.assertTrue(any("KI" in r for r in broken["decision"]["reasons"]))

    def test_short_audio_track_regression_pr1(self):
        """Audio ends earlier than video (PR #1): the cut must not keep an A/V length difference."""
        from clipmac_windows import render
        source = self.source(video=40, audio=39.4)
        out = render.cut(source, 10, 30, self.dir / "cut.mp4", threading.Event())
        _, _, v, a = render.stream_durations(render.probe(out))
        self.assertLess(abs(v - a), render.AV_TOLERANCE)

    def test_technical_check_flags_landscape_and_av(self):
        from clipmac_windows import render
        bad = self.source(video=10, audio=8, name="bad.mp4")
        errors = render.technical_check(bad, 10)
        self.assertTrue(any("1080x1920" in e for e in errors))
        self.assertTrue(any("A/V" in e for e in errors))
        self.assertEqual(render.technical_check(self.dir / "missing.mp4", 10), ["Ausgabe ist nicht decodierbar."])


if __name__ == "__main__":
    unittest.main()
