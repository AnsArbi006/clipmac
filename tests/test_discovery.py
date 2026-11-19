import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from clipmac.engine import Engine
from clipmac.state import DEFAULTS, Store, save_settings


class DiscoveryTests(unittest.TestCase):
    def test_initial_top_ten_does_not_change_recurring_top_five(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "queue.sqlite")
            engine = Engine(store)
            engine.active.set()
            cfg = {**DEFAULTS, "streamers": ["example"]}
            now = datetime.now(timezone.utc).isoformat()
            clips = [{"id": f"clip{i}", "created_at": now, "view_count": 100-i,
                      "duration": 20, "video_id": "", "broadcaster_name": "example"}
                     for i in range(12)]
            # A consciously skipped clip must not be restored or backfilled.
            store.add(clips[0])
            store.update("clip0", "skipped")
            with patch("clipmac.engine.settings", return_value=cfg), \
                 patch("clipmac.engine.secrets", return_value={"client_id": "x", "client_secret": "y"}), \
                 patch("twitch_api.TwitchApiClient") as client:
                client.return_value.resolve_broadcasters.return_value = {"example": "123"}
                client.return_value.get_clips_for_broadcaster.return_value = clips
                initial = engine.discover(top_per_streamer=10)
                recurring = engine.discover()
            self.assertEqual(initial["added"], 9)
            self.assertEqual(recurring["limit"], 5)
            self.assertEqual(recurring["added"], 0)
            self.assertEqual(len(store.rows()), 10)
            self.assertEqual(store.get("clip0")["status"], "skipped")
            self.assertIsNone(store.get("clip10"))

    def test_zero_spacing_can_be_saved_negative_cannot(self):
        with tempfile.TemporaryDirectory() as tmp, patch("clipmac.state.RUNTIME", Path(tmp)):
            cfg = save_settings({"publish_interval_minutes": 0, "top_per_streamer": 5})
            self.assertEqual(cfg["publish_interval_minutes"], 0)
            with self.assertRaises(ValueError):
                save_settings({"publish_interval_minutes": -1})


if __name__ == "__main__":
    unittest.main()
