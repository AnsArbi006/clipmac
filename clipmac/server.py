import fcntl
import json
import os
import subprocess
import secrets as random_secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from pathlib import Path
from urllib.parse import urlparse

from .state import ROOT, RUNTIME, atomic_json, settings
from .engine import Engine
from . import publisher
from .live import LiveHighlights
from .long_highlights import LongHighlights
from .tiktok_service import TikTokController
from .environment import DEVELOPMENT, require_live


class LocalHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # This server is loopback-only; reverse DNS is unnecessary and can stall
        # startup on machines whose hostname resolver is unavailable.
        TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]


def serve(port=8768):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    process_lock = (RUNTIME / "app.lock").open("w")
    try:
        fcntl.flock(process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError(f"ClipMac läuft schon: http://127.0.0.1:{port}")
    engine = Engine()
    tiktok = TikTokController(engine.store)
    live = LiveHighlights(RUNTIME / "live-highlights")
    highlights = LongHighlights(RUNTIME / "highlight-analysis")
    csrf = random_secrets.token_urlsafe(32)
    auth_running = threading.Event()
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, value, status=200, content_type="application/json; charset=utf-8"):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get("Host") in allowed_hosts

        def do_GET(self):
            if not self.valid_host():
                return self.send({"error": "Ungültiger Host"}, 403)
            path = urlparse(self.path).path
            if path == "/":
                html = (ROOT / "clipmac" / "ui.html").read_text().replace("__CSRF__", csrf)
                if DEVELOPMENT:
                    html = html.replace("<main>", '<main><p role="status" style="padding:16px;background:#294436;border-radius:12px">Entwicklungsmodus · Alle Daten sind synthetisch · Uploads und Kontoanmeldungen sind gesperrt</p>')
                return self.send(html.encode(), content_type="text/html; charset=utf-8")
            if DEVELOPMENT and path == "/dev-thumbnail.svg":
                return self.send((ROOT / "clipmac" / "dev-thumbnail.svg").read_bytes(), content_type="image/svg+xml")
            if path == "/layout":
                return self.send((ROOT / "clipmac" / "layout-preview.html").read_bytes(), content_type="text/html; charset=utf-8")
            if path == "/feedback-ui.js":
                return self.send((ROOT / "clipmac" / "feedback-ui.js").read_bytes(), content_type="text/javascript; charset=utf-8")
            if path in ("/learning-ui.js", "/learning.css", "/gallery.js", "/gallery.css", "/tiktok-ui.js", "/tiktok.css",
                        "/live-ui.js", "/highlights.css", "/highlight-ui.js"):
                mime = "text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
                return self.send((ROOT / "clipmac" / path[1:]).read_bytes(), content_type=mime)
            if path == "/api/learning/export":
                from .learning import learning_export
                return self.send(learning_export(engine.store))
            if path == "/api/state":
                return self.send({**engine.snapshot(), "auth_running": auth_running.is_set(),
                                  "development": DEVELOPMENT,
                                  "demo_ready": (RUNTIME / "demo" / "final.mp4").exists()})
            if path == "/api/tiktok/state":
                try:
                    return self.send(tiktok.snapshot())
                except Exception:
                    return self.send({"error": "TikTok-Status konnte nicht gelesen werden. Lokale Daten prüfen."}, 500)
            if path == "/api/live/state":
                return self.send({**live.snapshot(settings()), "development": DEVELOPMENT})
            if path == "/api/highlights/state":
                return self.send({**highlights.snapshot(), "development": DEVELOPMENT})
            if path.startswith("/highlight-video/"):
                try:
                    return self.video(highlights.preview(path.removeprefix("/highlight-video/")))
                except (ValueError, OSError):
                    return self.send({"error": "Vorschau nicht verfügbar."}, 404)
            if path.startswith("/feedback/"):
                import re
                match = re.fullmatch(r"/feedback/([a-f0-9]{32})/((?:output|source)-[0-2]\.jpg)", path)
                if match:
                    file = RUNTIME / "feedback" / match[1] / match[2]
                    if file.is_file():
                        return self.send(file.read_bytes(), content_type="image/jpeg")
                return self.send({"error": "Vergleichsbild nicht gefunden"}, 404)
            if path.startswith("/video/"):
                clip_id = path.removeprefix("/video/")
                job = engine.store.get(clip_id)
                file = RUNTIME / "clips" / clip_id / "final.mp4" if job else None
                if clip_id == "demo":
                    file = RUNTIME / "demo" / "final.mp4"
                if clip_id == "style-preview":
                    file = RUNTIME / "style-preview" / "preview.mp4"
                previews = {"layout-third": "third", "layout-half": "half", "layout-trymacs": "trymacs", "layout-switch": "switch"}
                if clip_id in previews:
                    file = RUNTIME / "layout-preview" / previews[clip_id] / "final.mp4"
                if file and file.is_file():
                    return self.video(file)
            return self.send({"error": "Nicht gefunden"}, 404)

        def video(self, path):
            size = path.stat().st_size
            start, end = 0, size - 1
            header = self.headers.get("Range", "")
            if header:
                import re
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", header)
                if not match:
                    return self.send({"error": "Ungültiger Byte-Bereich"}, 416)
                start = int(match[1])
                end = min(int(match[2]) if match[2] else end, end)
                if start > end:
                    return self.send({"error": "Ungültiger Byte-Bereich"}, 416)
            self.send_response(206 if header else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if header:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with path.open("rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining:
                    block = f.read(min(256 * 1024, remaining))
                    if not block:
                        break
                    try:
                        self.wfile.write(block)
                    except (BrokenPipeError, ConnectionResetError):
                        break
                    remaining -= len(block)

        def do_POST(self):
            origin = self.headers.get("Origin")
            if not self.valid_host() or self.headers.get("X-ClipMac-Token") != csrf or (origin and urlparse(origin).netloc not in allowed_hosts):
                return self.send({"error": "Bitte die lokale ClipMac-Seite verwenden."}, 403)
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 65536:
                    raise ValueError("Ungültige Anfragegröße")
                body = json.loads(self.rfile.read(length))
                path = urlparse(self.path).path
                if path in {"/api/twitch", "/api/youtube-client", "/api/youtube-connect",
                            "/api/reconcile"}:
                    require_live("Kontozugriff")
                if path == "/api/highlights/start":
                    kind = body.get("kind")
                    if kind == "vod":
                        require_live("Twitch-VOD herunterladen")
                    if kind not in {"local", "vod"}:
                        raise ValueError("Bitte lokale Datei oder Twitch-VOD wählen.")
                    job = highlights.start(body.get("source", ""), kind, settings())
                    return self.send({"ok": True, "job": job})
                elif path == "/api/highlights/analyze-live":
                    require_live("Live-Kandidat analysieren")
                    cfg = settings()
                    candidate = next((row for row in live.snapshot(cfg)["candidates"] if row["id"] == body.get("id")), None)
                    if candidate is None:
                        raise ValueError("Live-Kandidat ist nicht verfügbar.")
                    job = highlights.start_live(candidate, live.export, cfg)
                    return self.send({"ok": True, "job": job})
                elif path == "/api/highlights/cancel":
                    highlights.cancel(body.get("id"))
                elif path == "/api/highlights/render":
                    highlights.render(body.get("id"))
                elif path == "/api/live/start":
                    require_live("Live-Aufnahme und Twitch-Chat")
                    live.start(body.get("channel"), settings())
                elif path == "/api/live/stop":
                    live.stop(body.get("channel"))
                elif path == "/api/live/chat-credentials":
                    require_live("Twitch-Chat-Zugang speichern")
                    import re
                    login = body.get("login", "").strip().lower()
                    access = body.get("access_token", "").strip().removeprefix("oauth:")
                    if not re.fullmatch(r"[a-z0-9_]{3,25}", login) or not re.fullmatch(r"[A-Za-z0-9]{20,200}", access):
                        raise ValueError("Bitte Twitch-Login und einen gültigen Benutzer-Token mit chat:read angeben.")
                    atomic_json(RUNTIME / "credentials" / "twitch_chat.json",
                                {"login": login, "access_token": access}, private=True)
                elif path == "/api/tiktok/start":
                    tiktok.start("upload")
                elif path == "/api/tiktok/stop":
                    tiktok.stop()
                elif path == "/api/tiktok/check":
                    tiktok.start("check")
                elif path == "/api/tiktok/connect":
                    tiktok.start("connect")
                elif path == "/api/start":
                    engine.start()
                elif path == "/api/pause":
                    engine.pause()
                elif path == "/api/scan":
                    if not engine.active.is_set():
                        raise ValueError("Bitte zuerst die Automatik starten.")
                    engine.scan_requested.set()
                elif path == "/api/settings":
                    from .state import save_settings
                    if auth_running.is_set():
                        raise ValueError("Bitte die laufende Google-Anmeldung abschließen.")
                    save_settings(body)
                elif path == "/api/twitch":
                    if not body.get("client_id", "").strip() or not body.get("client_secret", "").strip():
                        raise ValueError("Client-ID und Client-Secret fehlen.")
                    atomic_json(RUNTIME / "credentials" / "twitch.json",
                                {"client_id": body["client_id"].strip(), "client_secret": body["client_secret"].strip()}, private=True)
                elif path == "/api/youtube-client":
                    if auth_running.is_set():
                        raise ValueError("Anmeldung läuft bereits.")
                    publisher.save_client(body)
                elif path == "/api/youtube-connect":
                    if engine.active.is_set():
                        raise ValueError("Bitte vor einem Kanalwechsel die Automatik pausieren.")
                    if auth_running.is_set():
                        raise ValueError("Anmeldung läuft bereits im Browser.")
                    auth_running.set()
                    def auth():
                        try:
                            with engine.auth_lock:
                                title = publisher.connect()
                            engine.store.log(f"YouTube verbunden: {title}")
                        except Exception as exc:
                            engine.store.log(f"Google-Anmeldung: {str(exc)[:400]}")
                        finally:
                            auth_running.clear()
                    threading.Thread(target=auth, daemon=True).start()
                elif path == "/api/retry":
                    engine.retry(body["id"])
                elif path == "/api/skip":
                    engine.skip(body["id"])
                elif path == "/api/report":
                    report_id = engine.report_problem(body["id"], body.get("note"), body.get("position"))
                    return self.send({"ok": True, "report_id": report_id})
                elif path == "/api/report-withdraw":
                    engine.store.withdraw_report(body["report_id"])
                elif path == "/api/rating":
                    engine.store.rate(body["id"], body.get("value"))
                elif path == "/api/reconcile":
                    engine.reconcile(body["id"], body["video_id"])
                else:
                    return self.send({"error": "Nicht gefunden"}, 404)
                return self.send({"ok": True})
            except Exception as exc:
                return self.send({"error": str(exc)[:1000]}, 400)

    httpd = LocalHTTPServer(("127.0.0.1", port), Handler)
    sleep_guard = None
    if not DEVELOPMENT and Path("/usr/bin/caffeinate").is_file():
        sleep_guard = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())])
    engine.launch()
    tiktok.launch()
    engine.store.log(f"ClipMac bereit: http://127.0.0.1:{port} – Automatik ist pausiert.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        highlights.close()
        live.close()
        tiktok.stop()
        tiktok.shutdown.set()
        engine.pause()
        engine.shutdown.set()
        httpd.server_close()
        if sleep_guard is not None:
            sleep_guard.terminate()


if __name__ == "__main__":
    serve()
