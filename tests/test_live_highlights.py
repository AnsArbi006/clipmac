import csv
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from clipmac.live import LiveHighlights
from clipmac.live_buffer import LiveBuffer
from clipmac.live_capture import export_segments
from clipmac.live_chat import SpikeConfig, SpikeDetector, irc_message
from clipmac.media import binary, probe, run


LIVE = {"stream_id": "live01", "stream_started": 900, "category_id": "gta6", "category_name": "Grand Theft Auto VI"}
CFG = {"streamers": ["channel1", "channel2", "channel3"], "required_game_id": "gta6"}


class ChatSpikeTests(unittest.TestCase):
    def setUp(self):
        self.detector = SpikeDetector()
        self.detector.connect(0)

    def fill(self, at, participants, messages_per_participant):
        for user in range(participants):
            for _ in range(messages_per_participant):
                self.detector.message(at, str(user + 1))
        return self.detector.tick(at + 9)

    def test_quiet_baseline_and_diverse_burst(self):
        self.assertEqual(self.fill(1, 5, 3), [])
        for start in range(10, 180, 10):
            self.assertEqual(self.fill(start + 1, 0, 0), [])
        [event] = self.fill(181, 5, 3)
        self.assertEqual((event["received_at"], event["messages"], event["participants"]), (185, 15, 5))
        self.assertEqual(event["baseline_messages"], 0)
        self.assertEqual(event["strength_ratio"], 15)

    def test_spam_and_busy_baseline(self):
        for start in range(0, 180, 10):
            self.assertEqual(self.fill(start + 1, 20, 3), [])
        self.assertEqual(self.fill(181, 1, 1000), [])
        self.assertEqual(self.fill(191, 22, 3), [])

    def test_reconnect_resets_history_and_delayed_messages_do_not_create_burst(self):
        self.detector.tick(180)
        self.assertTrue(self.detector.warmed)
        self.detector.disconnect()
        self.detector.tick(999)
        self.detector.connect(1000)
        self.assertFalse(self.detector.warmed)
        self.assertEqual(self.fill(1001, 5, 3), [])
        self.detector.tick(1180)
        for user in range(5):
            for _ in range(3):
                self.detector.message(1181, str(user + 1), sent_at=1001)
        self.assertEqual(self.detector.tick(1190), [])

    def test_only_identifiers_and_timestamps_leave_parser(self):
        line = "@user-id=14;tmi-sent-ts=1733434433000 :test!host PRIVMSG #channel1 :super secret text"
        self.assertEqual(irc_message(line, "channel1"), ("14", 1733434433.0))
        self.assertIsNone(irc_message(line, "channel2"))
        self.assertIsNone(irc_message(line.replace("user-id=14", "user-id="), "channel1"))
        for settings in ({"window_seconds": 0}, {"baseline_seconds": 24}, {"unexpected": 8}, {"rate_multiple": True}):
            with self.assertRaises(ValueError):
                SpikeConfig.from_settings({"live_spike": settings})


class BufferTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.buffer = LiveBuffer(Path(folder.name) / "live", limit=200, free_min=50, headroom=2,
                                 disk_usage=lambda _: SimpleNamespace(free=100))
        self.session, self.directory = self.buffer.begin("channel1", LIVE, CFG, 990)

    def segments(self, count, missing=()):
        for n in range(count):
            if n in missing:
                continue
            name = f"{n:08}.ts"
            (self.directory / name).write_bytes(b"test-segment")
            self.buffer.add_segment(self.session, name, n * 5, (n + 1) * 5, 1000 + (n + 1) * 5)

    def trigger(self, received=1041):
        return self.buffer.trigger(self.session, {"received_at": received, "strength_ratio": 4}, 6)

    def test_context_is_reserved_until_export_and_can_survive_restart(self):
        self.segments(14)
        key = self.trigger()
        self.buffer.observe_category(self.session, LIVE, 1070)
        self.assertEqual((self.buffer.candidates[key]["start"], self.buffer.candidates[key]["end"]), (1005, 1065))
        self.assertEqual(self.buffer.candidates[key]["coverage"], "complete")
        self.assertFalse(self.buffer.candidates[key]["category_review"])
        self.buffer.end(self.session)
        restored = LiveBuffer(self.buffer.root)
        restored.prune(1500)
        self.assertEqual(len(restored.sessions[self.session]["segments"]), 12)
        destination = self.directory.parent / "export.mp4"
        attempts = []

        def export(directory, segments, offset, duration, output, cancel):
            attempts.append((len(segments), offset, duration))
            if cancel.is_set():
                raise RuntimeError("cancelled")
            return output

        controller = LiveHighlights(buffer=restored, exporter=export)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            controller.export(key, destination, cancel)
        self.assertEqual(restored.candidates[key]["coverage"], "complete")
        self.assertEqual(controller.export(key, destination), destination)
        self.assertEqual(attempts[-1], (12, 0, 60))
        restored.prune(1501)
        self.assertEqual(restored.bytes_used(), 0)

    def test_missing_segment_and_category_change_fail_closed(self):
        self.segments(14, missing=(8,))
        key = self.trigger()
        self.buffer.observe_category(self.session, {**LIVE, "category_id": "other"}, 1050)
        self.buffer.observe_category(self.session, {**LIVE, "category_id": "other"}, 1070)
        row = self.buffer.public_candidates()[0]
        self.assertEqual(row["id"], key)
        self.assertEqual(row["coverage"], "incomplete")
        self.assertTrue(row["category_review"])
        self.assertIsNone(row["category_id"])

    def test_nearby_triggers_merge_and_never_cross_session(self):
        self.segments(12)
        key = self.trigger()
        self.assertEqual(self.trigger(received=1081), key)
        self.assertEqual(self.buffer.candidates[key]["end"] - self.buffer.candidates[key]["start"], 100)
        self.assertNotEqual(self.trigger(received=1120), key)
        other, _ = self.buffer.begin("channel1", {**LIVE, "stream_id": "second"}, CFG, 1100)
        again = self.buffer.trigger(other, {"received_at": 1121, "strength_ratio": 5}, 6)
        self.assertNotEqual(again, key)
        self.assertEqual(self.buffer.candidates[again]["session"], other)

    def test_low_disk_and_unfinished_capture_are_protected(self):
        path = self.directory / "00000003.ts"
        path.write_bytes(bytes(199))
        self.assertFalse(self.buffer.has_room(1001))
        self.assertTrue(path.is_file())
        self.assertEqual(self.buffer.bytes_used(), 199)
        self.buffer.end(self.session)
        self.buffer.disk_usage = lambda _: SimpleNamespace(free=20)
        self.assertFalse(self.buffer.has_room(1002))
        self.assertFalse(path.exists())


class LiveControllerTests(unittest.TestCase):
    def test_two_slots_stop_and_restart_without_autostart(self):
        with tempfile.TemporaryDirectory() as folder:
            buffer = LiveBuffer(Path(folder), free_min=0, headroom=0)
            active = set()
            lock = threading.Lock()

            class Capture:
                running = True

                def __init__(self, channel, directory):
                    self.channel = channel
                    with lock:
                        active.add(channel)

                def completed(self):
                    return ()

                def close(self):
                    with lock:
                        active.remove(self.channel)

            class Chat:
                joined = True

                def __init__(self, *_):
                    pass

                def read(self):
                    threading.Event().wait(0.01)
                    return []

                def close(self):
                    pass

            service = LiveHighlights(buffer=buffer, lookup=lambda _: LIVE, capture=Capture, chat=Chat)
            self.addCleanup(service.close)
            self.assertTrue(all(row["state"] == "off" for row in service.snapshot(CFG)["channels"]))
            with patch("clipmac.live.RECONNECT_PAUSE", 0.05):
                for channel in CFG["streamers"]:
                    service.start(channel, CFG)
                limit = time.monotonic() + 2
                while len(active) < 2 and time.monotonic() < limit:
                    threading.Event().wait(0.01)
                self.assertEqual(len(active), 2)
                waiting = next(c for c in CFG["streamers"] if c not in active)
                selected = next(iter(active))
                service.stop(selected)
                limit = time.monotonic() + 2
                while waiting not in active and time.monotonic() < limit:
                    threading.Event().wait(0.01)
                self.assertIn(waiting, active)
                self.assertNotIn(selected, active)
            service.close()
            self.assertEqual(active, set())
            reopened = LiveHighlights(buffer=LiveBuffer(Path(folder)))
            self.assertTrue(all(row["state"] == "off" for row in reopened.snapshot(CFG)["channels"]))


class LiveFFmpegTests(unittest.TestCase):
    def test_segmented_synthetic_input_and_exact_export(self):
        try:
            ffmpeg = binary("ffmpeg")
        except RuntimeError as exc:
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            response = run([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
                            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:d=12",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
                            "-c:v", "libx264", "-threads", "2", "-preset", "ultrafast", "-g", "150",
                            "-force_key_frames", "expr:gte(t,n_forced*5)", "-c:a", "aac",
                            "-f", "segment", "-segment_time", "5", "-segment_format", "mpegts",
                            "-reset_timestamps", "1", "-segment_list", "pipe:1", "-segment_list_type", "csv",
                            "%08d.ts"], cwd=directory)
            segments = [{"name": name, "start": float(start), "end": float(end)}
                        for name, start, end in csv.reader(response.stdout.splitlines())]
            self.assertEqual(len(segments), 3)
            destination = directory / "candidate.mp4"
            export_segments(directory, segments[:2], 2, 7, destination, threading.Event())
            self.assertAlmostEqual(float(probe(destination)["format"]["duration"]), 7, delta=0.10)
