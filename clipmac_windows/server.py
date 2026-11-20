"""Local dashboard server (127.0.0.1 only). Plain stdlib, no external web framework."""

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import PLATFORMS

STATIC = Path(__file__).resolve().parent / "static"
FILES = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
         "/app.css": ("app.css", "text/css; charset=utf-8")}
MEDIA = {"final": ("final.mp4", "video/mp4"), "original": ("original.mp4", "video/mp4"),
         "thumb": ("thumb.jpg", "image/jpeg")}
CLIP_ID = re.compile(r"[0-9a-f]{32}\Z")


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _host_ok(self):
            host = self.headers.get("Host", "")
            return re.fullmatch(r"(127\.0\.0\.1|localhost)(:\d+)?", host) is not None

        def _send(self, status, body, kind="application/json; charset=utf-8", extra=None):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "Nur lokal erreichbar."})
            path = self.path.split("?", 1)[0]
            if path in FILES:
                name, kind = FILES[path]
                return self._send(200, (STATIC / name).read_bytes(), kind,
                                  {"Content-Security-Policy": "default-src 'self'; media-src 'self'; img-src 'self'"})
            if path == "/api/state":
                return self._send(200, engine.snapshot())
            match = re.fullmatch(r"/media/([0-9a-f]{32})/(final|original|thumb)", path)
            if match:
                return self._media(*match.groups())
            self._send(404, {"error": "Nicht gefunden."})

        do_HEAD = do_GET

        def _media(self, clip_id, kind):
            name, mime = MEDIA[kind]
            file = engine.root / "clips" / clip_id / name
            if not file.is_file() or file.is_symlink():
                return self._send(404, {"error": "Datei fehlt."})
            size = file.stat().st_size
            start, end = 0, size - 1
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            status = 200
            if match and (match.group(1) or match.group(2)):
                if match.group(1):
                    start = int(match.group(1))
                    end = min(size - 1, int(match.group(2))) if match.group(2) else size - 1
                else:
                    start = max(0, size - int(match.group(2)))
                if start > end:
                    return self._send(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
                status = 206
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD":
                return
            with file.open("rb") as handle:
                handle.seek(start)
                left = end - start + 1
                try:
                    while left > 0:
                        chunk = handle.read(min(1 << 16, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
                except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                    pass

        def do_POST(self):
            # Same-origin JSON only: blocks cross-site form posts against the local server.
            if (not self._host_ok() or self.headers.get("X-ClipMac") != "1"
                    or not self.headers.get("Content-Type", "").startswith("application/json")):
                return self._send(403, {"error": "Anfrage abgelehnt."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(min(length, 65536)) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._send(400, {"error": "Ungültige Anfrage."})
            try:
                result = self._action(self.path, body)
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            self._send(200, result if isinstance(result, dict) else {"ok": bool(result)})

        def _action(self, path, body):
            if path == "/api/start":
                engine.start()
                return True
            if path == "/api/stop":
                engine.stop()
                return True
            if path == "/api/select":
                channels = body.get("channels")
                if (not isinstance(channels, list) or not 1 <= len(channels) <= 2 or len(set(channels)) != len(channels)
                        or any(c not in engine.cfg["streamers"] for c in channels)):
                    raise ValueError("Bitte ein oder zwei Streamer aus der Liste wählen.")
                if engine.running.is_set():
                    raise ValueError("Zum Ändern der Auswahl zuerst stoppen.")
                engine.save_settings(selected=channels)
                return True
            if path == "/api/settings":
                changes = {}
                if "score_threshold" in body:
                    value = body["score_threshold"]
                    if type(value) is not int or not 0 <= value <= 100:
                        raise ValueError("Schwelle muss 0-100 sein.")
                    changes["score_threshold"] = value
                if "upload_enabled" in body:
                    if type(body["upload_enabled"]) is not bool:
                        raise ValueError("Ungültiger Upload-Schalter.")
                    changes["upload_enabled"] = body["upload_enabled"]
                if "platforms_enabled" in body:
                    value = body["platforms_enabled"]
                    if not isinstance(value, list) or any(p not in PLATFORMS for p in value):
                        raise ValueError("Unbekannte Plattform.")
                    changes["platforms_enabled"] = [p for p in PLATFORMS if p in value]
                engine.save_settings(**changes)
                return True
            if path == "/api/retry":
                if not CLIP_ID.fullmatch(str(body.get("clip"))) or body.get("platform") not in PLATFORMS:
                    raise ValueError("Ungültiger Clip.")
                return engine.retry(body["clip"], body["platform"])
            if path == "/api/confirm":
                if body.get("platform") not in PLATFORMS:
                    raise ValueError("Unbekannte Plattform.")
                return engine.confirm_account(body["platform"])
            raise ValueError("Unbekannte Aktion.")

    return Handler


def serve(engine, port=8765):
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(engine))
    server.daemon_threads = True
    return server
