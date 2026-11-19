"""Isolated dashboard with synthetic records, no accounts or upload workers."""
import argparse
from datetime import datetime, timezone
import os
import time


def seed(with_video=False):
    from .environment import DEVELOPMENT
    if not DEVELOPMENT:
        raise RuntimeError("Synthetische Daten nur mit python -m clipmac.dev erzeugen.")
    from .state import RUNTIME, Store, DEFAULTS, atomic_json
    store = Store()
    if not (RUNTIME / "settings.json").exists():
        atomic_json(RUNTIME / "settings.json", {**DEFAULTS, "streamers": ["demo_creator"],
                    "publish_enabled": False, "publish_batch_size": 5})
    for index, status in enumerate(("ready", "published", "failed"), start=1):
        clip_id = f"synthetic-{index}"
        folder = RUNTIME / "clips" / clip_id
        if store.get(clip_id):
            continue
        folder.mkdir(parents=True, exist_ok=True)
        now = time.time()
        clip = {"id": clip_id, "broadcaster_name": "Demo Creator", "streamer_login": "demo_creator",
                "title": f"Synthetisches Beispiel {index}", "duration": 4, "view_count": 100 * index,
                "thumbnail_url": "/dev-thumbnail.svg", "url": "", "video_id": "", "game_name": "Demo",
                "created_at": datetime.fromtimestamp(now, timezone.utc).isoformat()}
        store.add(clip)
        if with_video:
            from .media import binary, run
            run([binary("ffmpeg"), "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                 "testsrc2=size=360x640:rate=15", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                 "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", folder / "final.mp4"], timeout=60)
        result = {"file": str(folder / "final.mp4") if with_video else "", "render": {"width": 360, "height": 640, "duration": 4},
                  "metadata": {"title": clip["title"], "description": "#SyntheticDemo", "tags": ["SyntheticDemo"]},
                  "synthetic": True}
        store.update(clip_id, status, result=result, error="Synthetischer Fehler zum Testen" if status == "failed" else "",
                     youtube_id="synthetic-video" if status == "published" else "", published=now-9000 if status == "published" else None)
        if status == "published":
            job = store.get(clip_id)
            for age, views, likes in ((3660, 120, 4), (7260, 290, 9)):
                store.record_performance(job, {"availability": "public", "views": views, "likes": likes, "comments": 2},
                                         now-9000+age, now-9000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", help="Leeres oder bereits als Entwicklung markiertes Verzeichnis")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--with-video", action="store_true", help="FFmpeg erzeugt vier Sekunden Farbmuster mit Testton")
    parser.add_argument("--seed-only", action="store_true")
    args = parser.parse_args()
    os.environ["CLIPMAC_DEV"] = "1"
    if args.data_dir:
        os.environ["CLIPMAC_DATA_DIR"] = args.data_dir
    from .environment import RUNTIME
    seed(args.with_video)
    print(f"Entwicklungsmodus · synthetische Daten · Uploads gesperrt\nDaten: {RUNTIME}", flush=True)
    if not args.seed_only:
        from .server import serve
        print(f"Dashboard: http://127.0.0.1:{args.port}", flush=True)
        serve(args.port)


if __name__ == "__main__":
    main()
