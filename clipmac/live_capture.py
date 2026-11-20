"""Media and authenticated Twitch adapters for the live recorder."""

import csv
import json
import math
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime

from .environment import RUNTIME, require_live
from .live_chat import ChatConnection
from .media import binary
from .state import secrets


SEGMENT_SECONDS = 5
SEGMENT_NAME = re.compile(r"[0-9]{8}\.ts\Z")


def open_chat(channel):
    require_live("Live-Chat-Verbindung")
    try:
        credentials = json.loads((RUNTIME / "credentials" / "twitch_chat.json").read_text(encoding="utf-8"))
        login, token = credentials["login"], credentials["access_token"]
        if not isinstance(login, str) or not isinstance(token, str):
            raise ValueError
    except (OSError, KeyError, ValueError, TypeError):
        raise ValueError("Twitch-Chat-Zugang fehlt. Login und Benutzer-Token mit chat:read einrichten.") from None
    return ChatConnection(channel, login, token.removeprefix("oauth:"))


class StreamLookup:
    def __init__(self):
        self.credentials = None
        self.client = None
        self.lock = threading.Lock()

    def __call__(self, channel):
        require_live("Live-Status bei Twitch abfragen")
        from twitch_api import TwitchApiClient

        credentials = secrets()
        if not credentials.get("client_id") or not credentials.get("client_secret"):
            raise ValueError("Bitte zuerst den Twitch-Zugang für Helix einrichten.")
        with self.lock:
            if credentials != self.credentials:
                self.client = TwitchApiClient(credentials["client_id"], credentials["client_secret"])
                self.credentials = credentials
            streams = self.client._helix_get("/streams", [("user_login", channel)]).get("data", [])
            if not streams:
                return None
            stream = streams[0]
            archive = None
            try:
                videos = self.client._helix_get("/videos", [("user_id", stream["user_id"]),
                                                           ("type", "archive"), ("first", "5")]).get("data", [])
                archive = next((v["id"] for v in videos if v.get("stream_id") == stream["id"]), None)
            except Exception:
                # Live detection also works with archive creation disabled.
                pass
        started_at = datetime.fromisoformat(stream["started_at"].replace("Z", "+00:00")).timestamp()
        return {"stream_id": str(stream["id"]), "stream_started": started_at,
                "category_id": str(stream.get("game_id") or ""), "category_name": str(stream.get("game_name") or ""),
                "vod_id": str(archive) if archive else None}


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
    def __init__(self, channel, directory):
        require_live("Livestream-Aufnahme")
        streamlink = shutil.which("streamlink")
        if streamlink is None:
            raise ValueError("Streamlink fehlt. Streamlink installieren und ClipMac erneut starten.")
        ffmpeg = binary("ffmpeg")
        self.pipe = self.encoder = self.reader = None
        self.events = queue.Queue(maxsize=32)
        self.overflow = False
        self.pipe = subprocess.Popen([streamlink, "--stdout", "--loglevel", "error",
                                      "--stream-timeout", "20", f"https://www.twitch.tv/{channel}",
                                      "720p,480p,best"], stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
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
                stderr=subprocess.DEVNULL, text=True, encoding="ascii", errors="replace")
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
                               "-f", "concat", "-safe", "0", "-i", str(concat),
                               "-ss", f"{first_offset:.6f}", "-t", f"{duration:.6f}",
                               "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-threads", "2",
                               "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
                               str(exported)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL) as process:
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
