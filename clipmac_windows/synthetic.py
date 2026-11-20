"""Synthetic streams, chat, transcript and model for the isolated development mode.

Nothing here opens a network connection. FFmpeg generates test pictures and tones.
"""

import queue
import random
import re
import subprocess
import threading
import time

from .live_capture import PROCESS_FLAGS, SEGMENT_SECONDS, binary

CYCLE = 240  # seconds per scripted chat cycle


class SyntheticLookup:
    """Both demo channels are live; the second switches category during each cycle."""

    def __init__(self, cfg, clock=time.time):
        self.cfg, self.clock, self.started = cfg, clock, clock()

    def __call__(self, channel):
        elapsed = (self.clock() - self.started) % CYCLE
        game_id, name = self.cfg["required_game_id"], self.cfg["required_game_name"]
        if channel == self.cfg["streamers"][1] and 200 <= elapsed < 230:
            game_id, name = "509658", "Just Chatting"
        return {"stream_id": f"demo-{channel}", "stream_started": self.started,
                "category_id": game_id, "category_name": name}


class SyntheticCapture:
    """Writes real 5-second MPEG-TS segments with FFmpeg test sources at live pace."""

    def __init__(self, channel, directory, size="640x360"):
        self.directory = directory
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.hue = sum(map(ord, channel)) % 360
        self.size = size
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        index, pts = 0, 0.0
        next_due = time.monotonic() + SEGMENT_SECONDS
        while not self.stop.is_set():
            name = f"{index:08d}.ts"
            subprocess.run([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                            "-f", "lavfi", "-i", f"testsrc2=size={self.size}:rate=30:duration={SEGMENT_SECONDS}",
                            "-f", "lavfi", "-i", f"sine=frequency={220 + index % 5 * 110}:duration={SEGMENT_SECONDS}",
                            "-vf", f"hue=h={self.hue}", "-c:v", "libx264", "-preset", "ultrafast",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-shortest",
                            "-f", "mpegts", str(self.directory / name)],
                           stdin=subprocess.DEVNULL, creationflags=PROCESS_FLAGS, check=False)
            if self.stop.wait(max(0, next_due - time.monotonic())):
                break
            self.events.put((name, pts, pts + SEGMENT_SECONDS, time.time()))
            index, pts, next_due = index + 1, pts + SEGMENT_SECONDS, next_due + SEGMENT_SECONDS

    @property
    def running(self):
        return self.thread.is_alive()

    def completed(self):
        while True:
            try:
                yield self.events.get_nowait()
            except queue.Empty:
                break

    def close(self):
        self.stop.set()
        self.thread.join(timeout=10)


class SyntheticChat:
    """Scripted activity: normal, a real burst, single-user spam, quiet phase and a reconnect."""

    def __init__(self, channel, clock=time.time, burst_at=80, seed=None):
        self.channel, self.clock = channel, clock
        self.started = clock()
        self.last = self.started
        self.burst_at = burst_at
        self.random = random.Random(seed if seed is not None else channel)
        self.reconnected = set()

    def _rate(self, t):
        if self.burst_at <= t < self.burst_at + 10:
            return 6.0, 40          # burst: many participants
        if self.burst_at + 30 <= t < self.burst_at + 40:
            return 5.0, 1           # spam from one account
        if self.burst_at + 60 <= t < self.burst_at + 90:
            return 0.0, 1           # quiet
        return 0.4, 12              # normal activity

    def read(self):
        now = self.clock()
        messages = []
        t = self.last
        while t < now:
            elapsed = (t - self.started) % CYCLE
            cycle = int((t - self.started) // CYCLE)
            if 150 <= elapsed < 151 and cycle not in self.reconnected:
                self.reconnected.add(cycle)
                self.last = t + 1
                raise ConnectionError("Synthetischer Verbindungsabbruch.")
            rate, users = self._rate(elapsed)
            if self.random.random() < rate * 0.1:
                messages.append((t, str(1000 + self.random.randrange(users)), t - 0.3))
            t += 0.1
        self.last = now
        return messages

    def close(self):
        pass


SCRIPT = ("Okay Leute wir fahren jetzt zum Hafen. Da wartet angeblich die Polizei. "
          "Ich habe keine Ahnung was gleich passiert. Wir müssen den Wagen unbedingt abliefern. "
          "Pass auf da vorne ist eine Straßensperre. Ich versuche links vorbei zu fahren. "
          "Was? Nein! Das gibt es nicht! Er ist einfach über die Rampe gesprungen! "
          "Chat habt ihr das gesehen? Das war der beste Sprung des ganzen Streams. "
          "Okay wir sind sicher. Der Auftrag ist erledigt.")


def fake_transcribe(source, cfg, cancel):
    """Word times spread over the whole synthetic source, with a reaction near its middle."""
    from .render import probe
    duration = float(probe(source)["format"]["duration"])
    words, t, tokens = [], 0.5, SCRIPT.split()
    while t < duration - 1:
        for token in tokens:
            if t >= duration - 1:
                break
            length = 0.22 + 0.03 * len(token)
            words.append({"start": round(t, 3), "end": round(t + length, 3), "word": token})
            t += length + (0.6 if re.search(r"[.!?]$", token) else 0.12)
    return words


def fake_ask_factory(quality):
    """quality(channel) -> 'good' | 'weak' | 'broken'. Quotes are copied from the real units."""

    def ask(units, anchor, cfg, channel=None):
        level = quality(channel)
        if level == "broken":
            raise ValueError("Synthetisch ungültige Modellantwort.")
        first = anchor
        while first > 0 and units[anchor]["end"] - units[first - 1]["start"] <= 28:
            first -= 1
        last = anchor
        while last + 1 < len(units) and units[last + 1]["end"] - units[first]["start"] <= 45:
            last += 1
        values = {"good": (2, 2, 2), "weak": (1, 0, 0)}[level]
        pick = {"hook": first, "context": min(first + 1, last), "payoff": anchor}
        return {"first": first, "last": last,
                "criteria": {key: {"value": value, "unit": pick[key],
                                   "quote": " ".join(w["word"] for w in units[pick[key]]["words"][:3])}
                             for key, value in zip(("hook", "context", "payoff"), values)}}
    return ask
