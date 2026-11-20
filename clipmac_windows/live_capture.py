"""Media and authenticated Twitch adapters for the live recorder."""

import csv
import json
import math
import os
from http.client import HTTPSConnection, HTTPException
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from urllib.parse import urlencode

from .live_chat import ChatConnection, LOGIN


SEGMENT_SECONDS = 5
SEGMENT_NAME = re.compile(r"[0-9]{8}\.ts\Z")
PROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def binary(name):
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"{name} fehlt. Bitte FFmpeg und FFprobe zu PATH hinzufügen.")
    return executable


def read_credentials(root, filename, names):
    credentials = Path(root) / "credentials"
    path = credentials / filename
    if credentials.is_symlink() or path.is_symlink():
        raise ValueError("Bitte die Twitch-Zugangsdaten im Windows-Datenordner speichern.")
    raw = {}
    try:
        with path.open("rb") as file:
            raw = json.loads(file.read(16_385))
    except (OSError, ValueError):
        pass
    if (not isinstance(raw, dict) or
            any(not isinstance(raw.get(key), str) or not 1 <= len(raw[key]) <= 256 for key in names)):
        raise ValueError("Bitte zuerst die Twitch-Zugangsdaten im Windows-Dashboard speichern.")
    return tuple(raw[key] for key in names)


def open_chat(root, channel, *, live_allowed=False):
    if not live_allowed:
        raise PermissionError("Twitch-Chat ist im Testbetrieb gesperrt.")
    login, token = read_credentials(root, "twitch_chat.json", ("login", "access_token"))
    return ChatConnection(channel, login, token.removeprefix("oauth:"), live_allowed=True)


def twitch_json(host, method, path, *, body=None, headers=None):
    connection = HTTPSConnection(host, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        if response.status == 401:
            return 401, {}
        if response.status != 200:
            raise ConnectionError("Twitch-Status derzeit nicht verfügbar.")
        raw = response.read(65_537)
        data = json.loads(raw)
        if len(raw) > 65_536 or not isinstance(data, dict):
            raise ValueError
        return 200, data
    except (OSError, ValueError, HTTPException):
        raise ConnectionError("Twitch-Status derzeit nicht verfügbar. Zugang und Netzwerk prüfen.") from None
    finally:
        connection.close()


class StreamLookup:
    """Read the currently broadcasting stream and category via Helix."""

    def __init__(self, root, *, live_allowed=False, request=twitch_json, clock=time.monotonic):
        self.root = Path(root)
        self.live_allowed = live_allowed
        self.request, self.clock = request, clock
        self.credentials = self.token = None
        self.valid_until = 0
        self.lock = threading.Lock()

    def _app_token(self, credentials):
        if self.credentials == credentials and self.token and self.valid_until > self.clock():
            return self.token
        client_id, client_secret = credentials
        payload = urlencode({"client_id": client_id, "client_secret": client_secret,
                             "grant_type": "client_credentials"}).encode("ascii")
        status, response = self.request("id.twitch.tv", "POST", "/oauth2/token", body=payload,
                                        headers={"Content-Type": "application/x-www-form-urlencoded"})
        token, expiry = response.get("access_token"), response.get("expires_in")
        if (status != 200 or not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,256}", token)
                or type(expiry) is not int or expiry <= 0):
            raise ValueError("Twitch-App-Zugang ungültig. Client-ID und Client-Secret prüfen.")
        self.credentials, self.token = credentials, token
        self.valid_until = self.clock() + max(0, expiry - 30)
        return token

    def __call__(self, channel):
        if not self.live_allowed:
            raise PermissionError("Twitch-Status ist im Testbetrieb gesperrt.")
        if not isinstance(channel, str) or not LOGIN.fullmatch(channel):
            raise ValueError("Ungültiger Twitch-Kanal.")
        credentials = read_credentials(self.root, "twitch.json", ("client_id", "client_secret"))
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,256}", credentials[0]):
            raise ValueError("Bitte die Twitch-Client-ID prüfen.")
        with self.lock:
            for attempt in range(2):
                token = self._app_token(credentials)
                status, response = self.request(
                    "api.twitch.tv", "GET", "/helix/streams?" + urlencode({"user_login": channel}),
                    headers={"Client-Id": credentials[0], "Authorization": f"Bearer {token}"})
                if status != 401:
                    break
                self.token = None
            else:
                raise ValueError("Twitch-App-Zugang ungültig. Client-ID und Client-Secret prüfen.")
        try:
            streams = response["data"]
            if not isinstance(streams, list):
                raise TypeError
            if not streams:
                return None
            stream = streams[0]
            started_at = datetime.fromisoformat(stream["started_at"].replace("Z", "+00:00")).timestamp()
            if not stream["id"]:
                raise ValueError
            return {"stream_id": str(stream["id"]), "stream_started": started_at,
                    "category_id": str(stream.get("game_id") or ""),
                    "category_name": str(stream.get("game_name") or "")}
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            raise ConnectionError("Twitch hat keinen lesbaren Live-Status geliefert.") from None


def _finish(process, immediate=False):
    if process is None:
        return
    if immediate and process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


class SegmentCapture:
    def __init__(self, channel, directory, *, live_allowed=False):
        if not live_allowed:
            raise PermissionError("Streamlink ist im Testbetrieb gesperrt.")
        if not isinstance(channel, str) or not LOGIN.fullmatch(channel):
            raise ValueError("Ungültiger Twitch-Kanal.")
        streamlink = shutil.which("streamlink")
        if streamlink is None:
            raise ValueError("Streamlink fehlt. Streamlink installieren und ClipMac erneut starten.")
        ffmpeg = binary("ffmpeg")
        self.pipe = self.encoder = self.reader = None
        self.events = queue.Queue(maxsize=32)
        self.overflow = False
        self.pipe = subprocess.Popen([streamlink, "--no-config", "--stdout", "--loglevel", "error",
                                      "--stream-timeout", "20", f"https://www.twitch.tv/{channel}",
                                      "720p,480p,best"], stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=PROCESS_FLAGS)
        try:
            self.encoder = subprocess.Popen(
                [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", "pipe:0",
                 "-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=-2:'min(ih,720)'",
                 "-r", "30", "-c:v", "libx264", "-threads", "2", "-preset", "ultrafast",
                 "-pix_fmt", "yuv420p", "-maxrate", "4M", "-bufsize", "4M", "-g", "150", "-sc_threshold", "0",
                 "-force_key_frames", "expr:gte(t,n_forced*5)", "-c:a", "aac", "-b:a", "128k",
                 "-f", "segment", "-segment_time", str(SEGMENT_SECONDS), "-segment_format", "mpegts",
                 "-reset_timestamps", "1", "-segment_list", "pipe:1", "-segment_list_type", "csv",
                 "%08d.ts"], cwd=directory, stdin=self.pipe.stdout, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="ascii", errors="replace", creationflags=PROCESS_FLAGS)
            self.reader = threading.Thread(target=self._read_list, daemon=True)
            self.reader.start()
        except BaseException:
            self.close()
            raise
        finally:
            if self.pipe.stdout:
                self.pipe.stdout.close()

    def _read_list(self):
        for row in csv.reader(self.encoder.stdout):
            if len(row) != 3 or not SEGMENT_NAME.fullmatch(row[0]):
                continue
            try:
                start, end = float(row[1]), float(row[2])
                if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end:
                    continue
                self.events.put_nowait((row[0], start, end, time.time()))
            except (ValueError, queue.Full):
                self.overflow = True
                break

    @property
    def running(self):
        return not self.overflow and self.encoder.poll() is None

    def completed(self):
        while True:
            try:
                yield self.events.get_nowait()
            except queue.Empty:
                break

    def close(self):
        _finish(self.pipe, immediate=True)
        _finish(self.encoder)
        if self.reader is not None:
            self.reader.join(timeout=1)
        if self.encoder is not None and self.encoder.stdout:
            self.encoder.stdout.close()


def export_segments(directory, segments, first_offset, duration, destination, cancel):
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="live-export-", dir=destination.parent) as temporary:
        concat = Path(temporary) / "segments.ffconcat"
        exported = Path(temporary) / "candidate.mp4"
        lines = ["ffconcat version 1.0"]
        for segment in segments:
            name = segment["name"]
            if not SEGMENT_NAME.fullmatch(name):
                raise ValueError("Ungültiges Aufnahmesegment.")
            path = directory / name
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("Ein benötigtes Aufnahmesegment fehlt.")
            # ffconcat accepts absolute file URLs and quotes single quotes as shell-style text.
            value = path.resolve().as_posix().replace("'", "'\\''")
            lines.extend([f"file '{value}'", f"duration {segment['end'] - segment['start']:.6f}"])
        concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if cancel.is_set():
            raise RuntimeError("Export abgebrochen.")
        with subprocess.Popen([binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
                               "-protocol_whitelist", "file", "-f", "concat", "-safe", "0", "-i", str(concat),
                               "-ss", f"{first_offset:.6f}", "-t", f"{duration:.6f}",
                               "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-threads", "2",
                               "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
                               str(exported)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, creationflags=PROCESS_FLAGS) as process:
            deadline = time.monotonic() + 180
            try:
                while process.poll() is None:
                    if cancel.wait(0.15) or time.monotonic() >= deadline:
                        raise RuntimeError("Export abgebrochen oder Zeitlimit erreicht.")
            finally:
                if process.poll() is None:
                    _finish(process, immediate=True)
            if process.returncode or not exported.is_file() or not exported.stat().st_size:
                raise RuntimeError("FFmpeg konnte den Live-Ausschnitt nicht exportieren.")
        if cancel.is_set():
            raise RuntimeError("Export abgebrochen.")
        exported.replace(destination)
    return destination
