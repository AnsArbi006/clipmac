"""Read-only Twitch IRC input and bounded chat-window statistics."""

from collections import Counter, deque
from dataclasses import dataclass, fields
import math
import re
import socket
import ssl
from statistics import median
import time

from .environment import require_live


LOGIN = re.compile(r"[a-z0-9_]{3,25}\Z")


@dataclass(frozen=True)
class SpikeConfig:
    window_seconds: int = 10
    baseline_seconds: int = 180
    min_messages: int = 15
    min_participants: int = 5
    rate_multiple: float = 3
    mad_multiple: float = 3
    per_user_limit: int = 4

    @classmethod
    def from_settings(cls, cfg):
        raw = cfg.get("live_spike", {})
        if not isinstance(raw, dict) or raw.keys() - {f.name for f in fields(cls)}:
            raise ValueError("Ungültige Einstellungen zur Chat-Spitze.")
        value = cls(**raw)
        for name, low, high in (("window_seconds", 2, 60), ("baseline_seconds", 20, 600),
                                ("min_messages", 1, 10000), ("min_participants", 1, 1000),
                                ("per_user_limit", 1, 100), ("rate_multiple", 1, 100),
                                ("mad_multiple", 0, 100)):
            number = getattr(value, name)
            kind = (int, float) if name.endswith("multiple") else (int,)
            if type(number) not in kind or not low <= number <= high:
                raise ValueError(f"Ungültiger Wert für {name}.")
        if value.baseline_seconds % value.window_seconds or value.baseline_seconds < 2 * value.window_seconds:
            raise ValueError("Die Baseline braucht mindestens zwei ganze Chat-Fenster.")
        return value


class SpikeDetector:
    """Assign observed messages to receipt-time windows. Store counts after closure."""

    def __init__(self, cfg=None):
        self.cfg = cfg or SpikeConfig()
        self.history = deque(maxlen=self.cfg.baseline_seconds // self.cfg.window_seconds)
        self.current = Counter()
        self.start = None

    @property
    def warmed(self):
        return len(self.history) == self.history.maxlen

    def connect(self, at):
        self.disconnect()
        self.start = at

    def disconnect(self):
        self.history.clear()
        self.current.clear()
        self.start = None

    def message(self, at, user, sent_at=None):
        events = self.tick(at)
        if (self.start is not None and at >= self.start and user
                and (sent_at is None or -5 <= at - sent_at <= 3 * self.cfg.window_seconds)
                and (user in self.current or len(self.current) < 10_000)
                and self.current[user] < self.cfg.per_user_limit):
            self.current[user] += 1
        return events

    def tick(self, at):
        events = []
        cfg = self.cfg
        if self.start is None or not math.isfinite(at):
            return events
        if at - self.start > cfg.baseline_seconds + cfg.window_seconds:
            # A sleeping or stalled process did not observe these intervals.
            self.connect(at)
            return events
        while at >= self.start + cfg.window_seconds:
            count, breadth = sum(self.current.values()), len(self.current)
            if self.warmed and count >= cfg.min_messages and breadth >= cfg.min_participants:
                past_counts, past_breadth = zip(*self.history)
                baseline = median(past_counts)
                breadth_base = median(past_breadth)
                mad = median(abs(value - baseline) for value in past_counts)
                rate = count / max(1, baseline)
                deviation = (count - baseline) / max(1, mad)
                if rate >= cfg.rate_multiple and deviation >= cfg.mad_multiple:
                    events.append({"received_at": self.start + cfg.window_seconds / 2,
                                   "messages": count, "participants": breadth,
                                   "baseline_messages": baseline, "baseline_participants": breadth_base,
                                   "strength_ratio": rate, "participant_ratio": breadth / max(1, breadth_base),
                                   "mad": mad})
            self.history.append((count, breadth))
            self.start += cfg.window_seconds
            self.current.clear()
        return events


def irc_message(line, channel):
    tags, separator, remaining = line.partition(" ")
    if not separator or not tags.startswith("@"):
        return None
    _, _, command = remaining.partition(" ")
    if not command.startswith(f"PRIVMSG #{channel} :"):
        return None
    values = dict(field.split("=", 1) for field in tags[1:].split(";") if "=" in field)
    user = values.get("user-id", "")
    stamp = values.get("tmi-sent-ts", "")
    if not user.isascii() or not user.isdigit() or len(user) > 24:
        return None
    return user, int(stamp) / 1000 if stamp.isascii() and stamp.isdigit() and len(stamp) <= 16 else None


class ChatConnection:
    host = "irc.chat.twitch.tv"

    def __init__(self, channel, login, token):
        require_live("Live-Chat-Verbindung")
        if not LOGIN.fullmatch(login) or not LOGIN.fullmatch(channel) or not re.fullmatch(r"[A-Za-z0-9_\-]{8,256}", token):
            raise ValueError("Bitte Twitch-Chat-Login und Benutzer-Token mit chat:read prüfen.")
        self.channel = channel
        self.socket = None
        self.buffer = b""
        self.joined = False
        self.last_input = time.monotonic()
        raw = socket.create_connection((self.host, 6697), timeout=5)
        try:
            self.socket = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
            self.socket.sendall((f"PASS oauth:{token}\r\nNICK {login}\r\n"
                                 "CAP REQ :twitch.tv/tags twitch.tv/commands\r\n"
                                 f"JOIN #{channel}\r\n").encode("ascii"))
            self.socket.settimeout(0.1)
        except BaseException:
            self.close()
            raw.close()
            raise

    def close(self):
        if self.socket:
            self.socket.close()
            self.socket = None

    def read(self):
        """Return only IDs and timestamps for detector use. Drop all message text."""
        try:
            data = self.socket.recv(8192)
        except (socket.timeout, ssl.SSLWantReadError):
            if time.monotonic() - self.last_input > (360 if self.joined else 15):
                raise ConnectionError("Twitch-Chat antwortet nicht.")
            return []
        if not data:
            raise ConnectionError("Twitch-Chat getrennt.")
        at = time.time()
        self.last_input = time.monotonic()
        pieces = (self.buffer + data).split(b"\r\n")
        self.buffer = pieces.pop()
        if len(self.buffer) > 32_768:
            raise ConnectionError("Ungültige Twitch-Chat-Antwort.")
        messages = []
        for packet in pieces:
            line = packet.decode("utf-8", errors="replace")
            if line.startswith("PING "):
                self.socket.sendall(b"PONG :tmi.twitch.tv\r\n")
            elif re.match(r":\S+ RECONNECT\b", line):
                raise ConnectionError("Twitch fordert eine neue Chat-Verbindung an.")
            elif re.match(r":\S+ (?:NOTICE \*|CAP \S+ NAK)(?: |$)", line):
                raise ConnectionError("Twitch-Chat-Anmeldung abgelehnt. Token mit chat:read prüfen.")
            elif re.match(rf":\S+ 366 \S+ #{self.channel}(?: |$)", line):
                self.joined = True
            elif (message := irc_message(line, self.channel)) is not None and self.joined:
                messages.append((at, *message))
        return messages
