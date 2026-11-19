import tempfile
import unittest
from pathlib import Path

from clipmac.media import binary, cut_silence, probe, run
from clipmac.state import DEFAULTS


class SilenceFFmpegTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg = binary("ffmpeg")
            binary("ffprobe")
        except RuntimeError as exc:
            raise unittest.SkipTest(str(exc)) from exc

    def make_clip(self, path, sound, audio_seconds, audio_offset=0, audio_codec="pcm_s16le"):
        tone = f"aevalsrc=({sound})*0.3*sin(2*PI*440*t):s=48000:d={audio_seconds}"
        run([self.ffmpeg, "-hide_banner", "-nostdin", "-y",
             "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:d=4",
             "-itsoffset", audio_offset, "-f", "lavfi", "-i", tone,
             "-c:v", "mpeg4", "-c:a", audio_codec, path])

    def test_trailing_silence_with_different_stream_lengths(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mov"
            output = Path(directory) / "output.mp4"
            cases = [(4.0, 0, "pcm_s16le"), (3.97, 0, "pcm_s16le"),
                     (3.77, 0.2, "pcm_s16le"), (3.97, 0, "aac")]
            for audio_seconds, offset, codec in cases:
                with self.subTest(audio_seconds=audio_seconds, audio_offset=offset, audio_codec=codec):
                    sound = rf"lt(t\,{3.25 - offset:.2f})"
                    self.make_clip(source, sound, audio_seconds, offset, codec)
                    stream = next(s for s in probe(source)["streams"] if s["codec_type"] == "audio")
                    self.assertAlmostEqual(float(stream["duration"]), audio_seconds, delta=0.002)
                    self.assertAlmostEqual(float(stream["start_time"]), offset, delta=0.002)
                    cut = cut_silence(source, output, DEFAULTS)
                    [(start, end)] = cut["kept_intervals"]
                    self.assertEqual(start, 0)
                    self.assertAlmostEqual(end, 3.40, delta=0.002)
                    self.assertAlmostEqual(float(probe(output)["format"]["duration"]), end, delta=0.04)

    def test_short_audible_tail_after_interior_pause_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mov"
            output = Path(directory) / "output.mp4"
            self.make_clip(source, r"lt(t\,3.25)+gte(t\,3.94)", 3.97)
            self.assertEqual(cut_silence(source, output, DEFAULTS)["kept_intervals"], [(0.0, 4.0)])

    def test_entirely_silent_shorter_audio_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mov"
            output = Path(directory) / "output.mp4"
            self.make_clip(source, "0", 3.97)
            with self.assertRaisesRegex(RuntimeError, "fast nur Stille"):
                cut_silence(source, output, DEFAULTS)
