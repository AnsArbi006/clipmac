"""Windows entry point: python -m clipmac_windows [--demo] [--data-dir DIR] [--port 8765]

--demo uses synthetic streams, chat, transcript, model and simulated uploaders.
Without --demo the real Twitch/Streamlink/Whisper/Ollama/TikTok/YouTube adapters are used.
"""

import argparse
import logging
import os
import sys
import threading
import webbrowser

from . import config, pipeline, synthetic
from .engine import Adapters, Engine
from .uploaders import FakeUploader, TikTokUploader, YouTubeUploader, connect_youtube

DEMO_SPIKE = {"window_seconds": 10, "baseline_seconds": 60, "min_messages": 15, "min_participants": 5,
              "rate_multiple": 3, "mad_multiple": 3, "per_user_limit": 4}
DEMO_SCENARIOS = {"tiktok": ["review", "public", "unknown", "quota"], "youtube": ["public", "failed", "public"]}


def keep_awake(on):
    """Windows only: prevent sleep while recording (ES_CONTINUOUS | ES_SYSTEM_REQUIRED)."""
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))


def demo_adapters(cfg):
    quality = {cfg["streamers"][0]: "good", cfg["streamers"][1]: "weak"}
    scenarios = cfg.get("demo_scenarios") or DEMO_SCENARIOS
    return Adapters(lookup=synthetic.SyntheticLookup(cfg),
                    capture=lambda channel, directory: synthetic.SyntheticCapture(channel, directory),
                    chat=lambda channel: synthetic.SyntheticChat(channel),
                    transcribe=synthetic.fake_transcribe,
                    ask=synthetic.fake_ask_factory(lambda channel: quality.get(channel, "good")),
                    uploaders={p: FakeUploader(p, scenarios.get(p)) for p in config.PLATFORMS})


def live_adapters(root, cfg):
    from .live_capture import SegmentCapture, StreamLookup, open_chat
    uploaders = {}
    for name, cls in (("tiktok", TikTokUploader), ("youtube", YouTubeUploader)):
        uploaders[name] = cls(root, live_allowed=True)
    return Adapters(lookup=StreamLookup(root, live_allowed=True),
                    capture=lambda channel, directory: SegmentCapture(channel, directory, live_allowed=True),
                    chat=lambda channel: open_chat(root, channel, live_allowed=True),
                    transcribe=pipeline.whisper_transcribe, ask=pipeline.ollama_ask, uploaders=uploaders)


def main(argv=None):
    if os.name != "nt" and "--allow-non-windows" not in (argv or sys.argv):
        print("ClipMac Windows läuft nur unter Windows. (Für Tests: --allow-non-windows)")
        return 2
    parser = argparse.ArgumentParser(prog="clipmac_windows")
    parser.add_argument("--demo", action="store_true", help="Synthetische Streams und simulierte Uploads")
    parser.add_argument("--data-dir")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--connect-youtube", action="store_true", help="Lokale YouTube-Anmeldung starten")
    parser.add_argument("--allow-non-windows", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    root = config.data_root(args.data_dir, args.demo)
    if args.connect_youtube:
        connect_youtube(root, live_allowed=not args.demo)
        print("YouTube verbunden.")
        return 0
    cfg = config.settings(root)
    if args.demo:
        cfg.setdefault("live_spike", DEMO_SPIKE)
        cfg.setdefault("upload_enabled", True)
        cfg.setdefault("accounts", {p: "demo-konto" for p in config.PLATFORMS})
        cfg.setdefault("selected", cfg["streamers"][:2])
    with config.process_lock(root) if os.name == "nt" else _nolock():
        engine = Engine(root, cfg, demo_adapters(cfg) if args.demo else live_adapters(root, cfg), demo=args.demo)
        engine.service()
        from .server import serve
        server = serve(engine, args.port)
        url = f"http://127.0.0.1:{args.port}/"
        print(f"Dashboard: {url}  (Beenden mit Strg+C)")
        if not args.no_browser:
            threading.Timer(0.8, webbrowser.open, (url,)).start()
        keep_awake(True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            engine.stop()
            keep_awake(False)
            server.server_close()
    return 0


class _nolock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


if __name__ == "__main__":
    sys.exit(main())
