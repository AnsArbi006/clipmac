"""CM-012 A: chat spikes, live buffer, reservations and channel separation (synthetic, no network)."""

import tempfile
import unittest
from pathlib import Path

from clipmac_windows.live_buffer import LiveBuffer
from clipmac_windows.live_chat import SpikeConfig, SpikeDetector
from clipmac_windows.synthetic import SyntheticChat

CFG = {"required_game_id": "1867279146", "required_game_name": "Grand Theft Auto VI"}
GTA = {"stream_id": "s1", "stream_started": 0, "category_id": "1867279146", "category_name": "Grand Theft Auto VI"}


def feed(detector, start, seconds, per_window, users):
    events = []
    for w in range(seconds // 10):
        for i in range(per_window):
            events += detector.message(start + w * 10 + i * (9.0 / max(1, per_window)), str(i % users))
    events += detector.tick(start + seconds)
    return events


class SpikeTests(unittest.TestCase):
    def warm(self):
        d = SpikeDetector(SpikeConfig())
        d.connect(0)
        self.assertEqual(feed(d, 0, 180, 4, 4), [])
        self.assertTrue(d.warmed)
        return d

    def test_normal_activity_no_spike(self):
        d = self.warm()
        self.assertEqual(feed(d, 180, 60, 4, 4), [])

    def test_real_burst_detected_with_ratios(self):
        d = self.warm()
        events = feed(d, 180, 10, 40, 20) + d.tick(200)
        self.assertEqual(len(events), 1)
        self.assertGreaterEqual(events[0]["strength_ratio"], 3)
        self.assertEqual(events[0]["received_at"], 185)

    def test_spam_from_one_user_is_capped(self):
        d = self.warm()
        self.assertEqual(feed(d, 180, 10, 60, 1) + d.tick(200), [])

    def test_too_few_participants(self):
        d = self.warm()
        self.assertEqual(feed(d, 180, 10, 40, 4) + d.tick(200), [])

    def test_quiet_baseline_still_needs_minimum(self):
        d = SpikeDetector(SpikeConfig())
        d.connect(0)
        d.tick(180)
        self.assertTrue(d.warmed)
        self.assertEqual(feed(d, 180, 10, 10, 10) + d.tick(200), [])  # 10 < 15 messages
        self.assertEqual(len(feed(d, 200, 10, 15, 6) + d.tick(220)), 1)

    def test_reconnect_is_data_gap_and_rewarms(self):
        d = self.warm()
        d.disconnect()
        self.assertFalse(d.warmed)
        d.connect(500)
        self.assertEqual(feed(d, 500, 10, 40, 20) + d.tick(520), [])  # no baseline yet

    def test_stall_restarts_warmup(self):
        d = self.warm()
        d.tick(180 + 400)
        self.assertFalse(d.warmed)

    def test_settings_validation(self):
        with self.assertRaises(ValueError):
            SpikeConfig.from_settings({"live_spike": {"window_seconds": 10, "baseline_seconds": 15}})
        with self.assertRaises(ValueError):
            SpikeConfig.from_settings({"live_spike": {"unknown": 1}})

    def test_synthetic_chat_script(self):
        clock = [0.0]
        chat = SyntheticChat("papaplatte", clock=lambda: clock[0], burst_at=80, seed=1)
        d = SpikeDetector(SpikeConfig(baseline_seconds=60))
        d.connect(0)
        events, reconnects = [], 0
        for step in range(1, 240):
            clock[0] = float(step)
            try:
                for at, user, sent in chat.read():
                    events += d.message(at, user, sent)
            except ConnectionError:
                reconnects += 1
                d.disconnect()
                d.connect(clock[0])
            events += d.tick(clock[0])
        self.assertEqual(reconnects, 1)
        self.assertEqual(len(events), 1, events)          # burst yes, spam and quiet no
        self.assertTrue(80 <= events[0]["received_at"] <= 95)


class BufferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, name="a", info=GTA, segments=40, start=1000.0, free=10**12):
        buffer = LiveBuffer(self.root / name, disk_usage=lambda _: type("U", (), {"free": free})())
        sid, directory = buffer.begin(name, info, CFG, start)
        for i in range(segments):
            (directory / f"{i:08d}.ts").write_bytes(b"x" * 10)
            buffer.add_segment(sid, f"{i:08d}.ts", i * 5.0, i * 5.0 + 5, start + i * 5 + 5)
        return buffer, sid

    def test_delay_and_context_window(self):
        buffer, sid = self.session()
        key = buffer.trigger(sid, {"received_at": 1100, "strength_ratio": 4}, 6)
        c = buffer.candidates[key]
        self.assertEqual((c["trigger"], c["start"], c["end"]), (1094, 1064, 1124))
        self.assertEqual(c["coverage"], "complete")

    def test_merge_within_60s_and_cap_120s(self):
        buffer, sid = self.session(segments=60)
        a = buffer.trigger(sid, {"received_at": 1050, "strength_ratio": 4}, 6)
        b = buffer.trigger(sid, {"received_at": 1100, "strength_ratio": 6}, 6)
        self.assertEqual(a, b)
        self.assertEqual(buffer.candidates[a]["chat"]["strength_ratio"], 6)
        c = buffer.trigger(sid, {"received_at": 1150, "strength_ratio": 5}, 6)   # would exceed 120 s
        self.assertNotEqual(a, c)
        self.assertLessEqual(buffer.candidates[a]["end"] - buffer.candidates[a]["start"], 120)

    def test_channels_never_mix(self):
        one, sid1 = self.session("one")
        two, sid2 = self.session("two")
        k1 = one.trigger(sid1, {"received_at": 1100, "strength_ratio": 4}, 6)
        self.assertEqual(two.candidates, {})
        self.assertEqual(one.public_candidates()[0]["channel"], "one")
        self.assertIn(k1, one.candidates)

    def test_category_change_requires_review(self):
        buffer, sid = self.session(segments=10)
        buffer.observe_category(sid, {**GTA, "category_id": "509658", "category_name": "Just Chatting"}, 1030)
        key = buffer.trigger(sid, {"received_at": 1040, "strength_ratio": 4}, 6)
        buffer.observe_category(sid, GTA, 1100)
        self.assertTrue(buffer.candidates[key]["category_review"])

    def test_known_category_is_ok(self):
        buffer, sid = self.session()
        key = buffer.trigger(sid, {"received_at": 1100, "strength_ratio": 4}, 6)
        buffer.observe_category(sid, GTA, 1180)
        self.assertFalse(buffer.candidates[key]["category_review"])
        self.assertFalse(buffer.candidates[key]["category_pending"])

    def test_missing_segment_is_incomplete(self):
        buffer, sid = self.session(segments=40)
        (buffer.directory(sid) / "00000016.ts").unlink()
        key = buffer.trigger(sid, {"received_at": 1100, "strength_ratio": 4}, 6)
        buffer.end(sid)
        self.assertEqual(buffer.candidates[key]["coverage"], "incomplete")

    def test_prune_keeps_reserved_segments(self):
        buffer, sid = self.session(segments=40)
        key = buffer.trigger(sid, {"received_at": 1100, "strength_ratio": 4}, 6)
        buffer.prune(1200 + 300 + 100)
        left = {s["name"] for s in buffer.sessions[sid]["segments"]}
        self.assertTrue(buffer.coverage(buffer.candidates[key]))
        self.assertNotIn("00000000.ts", left)

    def test_low_disk_pauses(self):
        buffer, _ = self.session(free=4_000_000_000)
        self.assertFalse(buffer.has_room(1200))


if __name__ == "__main__":
    unittest.main()
