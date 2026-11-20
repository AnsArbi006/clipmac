"""Opt-in, per-channel Twitch live capture with a shared two-recorder limit."""

from dataclasses import dataclass, field
import math
from pathlib import Path
import threading
import time

from .environment import RUNTIME, require_live
from .live_buffer import LiveBuffer, RING_SECONDS
from .live_capture import SegmentCapture, StreamLookup, export_segments, open_chat
from .live_chat import LOGIN, SpikeConfig, SpikeDetector


MAX_RECORDERS = 2
OFFLINE_POLL = 60
CATEGORY_POLL = 15
RECONNECT_PAUSE = 5


@dataclass
class Channel:
    name: str
    stop: threading.Event = field(default_factory=threading.Event)
    state: str = "waiting"
    detail: str = "Live-Status wird geprüft."
    session: str | None = None
    thread: threading.Thread | None = None


class LiveHighlights:
    def __init__(self, root=RUNTIME / "live-highlights", *, lookup=None, capture=SegmentCapture,
                 chat=open_chat, exporter=export_segments, buffer=None):
        self.lock = threading.RLock()
        self.root = Path(root)
        self.buffer = buffer
        self.lookup = lookup or StreamLookup()
        self.capture = capture
        self.chat = chat
        self.exporter = exporter
        self.channels = {}
        self.recorder_slots = threading.BoundedSemaphore(MAX_RECORDERS)
        self.closed = False
        self.exports = {}

    def _open_buffer(self):
        if self.buffer is None:
            self.buffer = LiveBuffer(self.root)
        return self.buffer

    def snapshot(self, cfg):
        with self.lock:
            channels = []
            selected = cfg.get("streamers", [])
            for name, worker in self.channels.items():
                if name not in selected:
                    worker.stop.set()
            issue = ""
            try:
                buffer = self._open_buffer()
            except OSError:
                buffer = None
                issue = "Der Live-Puffer ist nicht lesbar."
            except RuntimeError as exc:
                buffer = None
                issue = str(exc)
            for name in selected:
                worker = self.channels.get(name)
                enabled = worker is not None and not worker.stop.is_set() and worker.thread.is_alive()
                session = buffer.sessions.get(worker.session) if worker and buffer else None
                segments = session["segments"] if session else []
                seconds = (segments[-1]["end"] - max(segments[0]["start"], segments[-1]["end"] - RING_SECONDS)) if segments else 0
                channels.append({"channel": name, "enabled": enabled,
                                 "state": worker.state if worker else "off",
                                 "detail": worker.detail if worker else "",
                                 "buffer_seconds": round(seconds, 1),
                                 "bytes": buffer.bytes_used(worker.session) if session else 0})
            return {"channels": channels, "candidates": buffer.public_candidates() if buffer else [],
                    "bytes": buffer.bytes_used() if buffer else 0, "limit_bytes": buffer.limit if buffer else 5_000_000_000,
                    "error": issue}

    def start(self, channel, cfg):
        require_live("Livestream-Aufnahme starten")
        if not isinstance(channel, str) or not LOGIN.fullmatch(channel) or channel not in cfg.get("streamers", []):
            raise ValueError("Bitte einen freigegebenen Streamer wählen.")
        spike = SpikeConfig.from_settings(cfg)
        delay = cfg.get("live_chat_delay_seconds", 6)
        if type(delay) not in (int, float) or not math.isfinite(delay) or not 0 <= delay <= 30:
            raise ValueError("Der Chat-Versatz muss zwischen 0 und 30 Sekunden liegen.")
        with self.lock:
            if self.closed:
                raise RuntimeError("Die Live-Aufnahme wird beendet.")
            self._open_buffer()
            previous = self.channels.get(channel)
            if previous is not None and previous.thread.is_alive():
                if previous.stop.is_set():
                    raise RuntimeError("Die letzte Aufnahme wird noch beendet.")
                return
            worker = Channel(channel)
            worker.thread = threading.Thread(target=self._watch, args=(worker, cfg.copy(), spike, delay),
                                             name=f"clipmac-live-{channel}", daemon=True)
            self.channels[channel] = worker
            worker.thread.start()

    def stop(self, channel):
        if not isinstance(channel, str) or not LOGIN.fullmatch(channel):
            raise ValueError("Ungültiger Twitch-Kanal.")
        with self.lock:
            worker = self.channels.get(channel)
            if worker and worker.thread.is_alive():
                worker.stop.set()
                self._state(worker, "stopping", "Aufnahme wird abgeschlossen.")

    def close(self):
        with self.lock:
            self.closed = True
            workers = list(self.channels.values())
            for worker in workers:
                worker.stop.set()
            for cancel in self.exports.values():
                cancel.set()
        deadline = time.monotonic() + 8
        for worker in workers:
            worker.thread.join(max(0, deadline - time.monotonic()))

    def _state(self, worker, state, detail=""):
        with self.lock:
            if worker.stop.is_set() and worker.state == "stopping" and state != "off":
                return
            worker.state, worker.detail = state, detail

    def _watch(self, worker, cfg, spike, delay):
        pause = 0
        try:
            while not worker.stop.wait(pause):
                pause = OFFLINE_POLL
                try:
                    info = self.lookup(worker.name)
                    if worker.stop.is_set():
                        break
                    if info is None:
                        self._state(worker, "offline", "Twitch-Live-Status wird nach 60 Sekunden erneut geprüft.")
                        continue
                    self._state(worker, "waiting", "Wartet auf einen der zwei Aufnahmeplätze.")
                    if not self.recorder_slots.acquire(blocking=False):
                        pause = RECONNECT_PAUSE
                        continue
                    try:
                        room = False
                        with self.lock:
                            room = self.buffer.has_room(time.time())
                        if room:
                            self._record(worker, cfg, info, spike, delay)
                        else:
                            self._state(worker, "paused", "Live-Puffer voll oder weniger als 5 GB freier Speicher.")
                        pause = RECONNECT_PAUSE
                    finally:
                        self.recorder_slots.release()
                except ValueError as exc:
                    # Adapter errors of this type are fixed operator instructions.
                    self._state(worker, "error", str(exc) if type(exc) is ValueError and exc.args else "Twitch-Konfiguration prüfen.")
                except Exception:
                    self._state(worker, "error", "Live-Aufnahme unterbrochen. Twitch, Streamlink und FFmpeg prüfen.")
        finally:
            self._state(worker, "off")

    def _collect(self, tape, session):
        for name, start, end, received in tape.completed():
            self.buffer.add_segment(session, name, start, end, received)
            self.buffer.save()

    def _record(self, worker, cfg, info, spike, delay):
        detection = SpikeDetector(spike)
        with self.lock:
            session, directory = self.buffer.begin(worker.name, info, cfg, time.time())
            worker.session = session
        tape = connection = None
        next_category = time.monotonic() + CATEGORY_POLL
        next_chat = 0
        next_space = 0
        try:
            tape = self.capture(worker.name, directory)
            while not worker.stop.is_set():
                clock = time.monotonic()
                now = time.time()
                with self.lock:
                    self._collect(tape, session)
                    if clock >= next_space:
                        next_space = clock + 0.25
                        if not self.buffer.has_room(now):
                            self._state(worker, "paused", "Live-Puffer voll oder weniger als 5 GB freier Speicher.")
                            return
                if not tape.running:
                    self._state(worker, "error", "Videostream beendet oder unterbrochen.")
                    return
                if clock >= next_category:
                    next_category = clock + CATEGORY_POLL
                    try:
                        updated = self.lookup(worker.name)
                    except Exception:
                        updated = {"stream_id": info["stream_id"], "category_id": None}
                    if not updated or updated["stream_id"] != info["stream_id"]:
                        return
                    with self.lock:
                        self.buffer.observe_category(session, updated, time.time())
                        self.buffer.save()
                if connection is None and clock >= next_chat:
                    try:
                        connection = self.chat(worker.name)
                        self._state(worker, "connected", "Video wird gepuffert. Chat-Verbindung wird geprüft.")
                    except (OSError, ValueError):
                        next_chat = time.monotonic() + RECONNECT_PAUSE
                        self._state(worker, "error", "Chat nicht erreichbar. Twitch-Login und Token mit chat:read prüfen.")
                if connection is None:
                    worker.stop.wait(0.1)
                    continue
                try:
                    messages = connection.read()
                except OSError:
                    connection.close()
                    connection = None
                    detection.disconnect()
                    next_chat = time.monotonic() + RECONNECT_PAUSE
                    self._state(worker, "connected", "Video zeichnet auf. Chat wird neu verbunden.")
                    continue
                if not connection.joined:
                    continue
                if detection.start is None:
                    detection.connect(min((row[0] for row in messages), default=time.time()))
                events = []
                for received, user, sent in messages:
                    events.extend(detection.message(received, user, sent))
                events.extend(detection.tick(time.time()))
                if events:
                    with self.lock:
                        for evidence in events:
                            self.buffer.trigger(session, evidence, delay)
                        self.buffer.save()
                if detection.warmed:
                    self._state(worker, "recording", "Chat-Spitzen werden erkannt.")
                else:
                    self._state(worker, "warming", "Sammelt Vergleichsdaten aus dem Chat.")
        finally:
            if connection is not None:
                connection.close()
            try:
                if tape is not None:
                    tape.close()
            finally:
                with self.lock:
                    try:
                        if tape is not None:
                            self._collect(tape, session)
                    finally:
                        self.buffer.end(session)
                        self.buffer.prune(time.time())

    def export(self, candidate_id, destination, cancel=None):
        """Render the reserved source interval. Release its reservation only on success."""
        cancel = cancel or threading.Event()
        with self.lock:
            buffer = self._open_buffer()
            if self.closed:
                raise RuntimeError("Der Live-Dienst wird beendet.")
            candidate = buffer.candidates.get(candidate_id)
            if not candidate or candidate["coverage"] != "complete":
                raise ValueError("Dieser Live-Ausschnitt steht nicht vollständig bereit.")
            if candidate_id in self.exports:
                raise ValueError("Dieser Live-Ausschnitt wird bereits exportiert.")
            segments = buffer.coverage(candidate)
            if not segments:
                raise ValueError("Ein benötigtes Live-Segment fehlt.")
            session = candidate["session"]
            start, end = candidate["start"], candidate["end"]
            directory = buffer.directory(session)
            self.exports[candidate_id] = cancel
            buffer.exporting.add(candidate_id)
        try:
            offset = max(0, start - segments[0]["start"])
            result = self.exporter(directory, segments, offset, end - start, destination, cancel)
            with self.lock:
                candidate["coverage"] = "exported"
                buffer.save()
            return result
        finally:
            with self.lock:
                del self.exports[candidate_id]
                buffer.exporting.remove(candidate_id)
