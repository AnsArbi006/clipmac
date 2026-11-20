"""Two recorders, one analysis/render worker and one publisher. Windows only, no Mac coordination."""

import logging
import queue as queuelib
import shutil
import threading
import time
from pathlib import Path

from . import pipeline
from .config import PLATFORMS, atomic_json
from .live_buffer import LIMIT_BYTES, LiveBuffer
from .live_capture import export_segments
from .live_chat import SpikeConfig, SpikeDetector
from .queue import Queue
from .uploaders import Pause

log = logging.getLogger("clipmac_windows")
LOOKUP_SECONDS = 60
REVIEW_CHECK_SECONDS = 60


class Adapters:
    """Everything that touches the outside world. Development mode injects synthetic versions."""

    def __init__(self, *, lookup, capture, chat, transcribe, ask, uploaders, disk_usage=shutil.disk_usage):
        self.lookup, self.capture, self.chat = lookup, capture, chat
        self.transcribe, self.ask, self.uploaders = transcribe, ask, uploaders
        self.disk_usage = disk_usage


class Channel:
    def __init__(self, name):
        self.name = name
        self.state = "gestoppt"
        self.live = False
        self.chat = "getrennt"
        self.recording = False
        self.messages_10s = 0
        self.baseline = None
        self.category = ""
        self.warning = ""
        self.spikes = 0

    def public(self):
        return dict(vars(self))


class Engine:
    def __init__(self, root, cfg, adapters, *, demo=False):
        self.root = Path(root)
        self.cfg = cfg
        self.adapters = adapters
        self.demo = demo
        self.queue = Queue(self.root / "clipmac-windows.sqlite")
        self.spike_cfg = SpikeConfig.from_settings(cfg)
        self.running = threading.Event()
        self.cancel = threading.Event()
        self.lock = threading.RLock()
        self.work = queuelib.Queue()
        self.channels = {}
        self.threads = []
        self.worker_state = {"stage": "bereit", "detail": "", "clip": None}
        self.platform_pause = {p: (0, "") for p in PLATFORMS}
        self.platform_account = {p: None for p in PLATFORMS}
        self.buffers = {}
        self.scheduled = set()
        self._service = None

    # ------------------------------------------------------------------ settings ----
    def save_settings(self, **changes):
        with self.lock:
            self.cfg.update(changes)
            keep = {k: self.cfg[k] for k in ("selected", "score_threshold", "platforms_enabled", "upload_enabled",
                                             "accounts", "reaction_delay", "live_spike", "ollama_model",
                                             "facecam_crops", "demo_scenarios") if k in self.cfg}
            atomic_json(self.root / "settings.json", keep)

    def selected(self):
        return [name for name in self.cfg.get("selected", self.cfg["streamers"][:2])
                if name in self.cfg["streamers"]][:2]

    # ------------------------------------------------------------------- control ----
    def start(self):
        with self.lock:
            if self.running.is_set():
                return
            self.running.set()
            self.cancel.clear()
            self.channels = {name: Channel(name) for name in self.selected()}
            self.threads = [threading.Thread(target=self._guard, args=(self._monitor, c), daemon=True,
                                             name=f"monitor-{c}") for c in self.channels]
            for thread in self.threads:
                thread.start()

    def stop(self):
        """No new recordings, analyses or posts. Submitted posts are still reconciled."""
        with self.lock:
            self.running.clear()
            self.cancel.set()
        for thread in self.threads:
            thread.join(timeout=15)
        self.threads = []
        while not self.work.empty():
            self.work.get_nowait()
        self.scheduled.clear()

    def service(self):
        """Background worker and publisher run for the process lifetime."""
        if self._service is None:
            self._service = [threading.Thread(target=self._guard, args=(self._worker,), daemon=True, name="worker"),
                             threading.Thread(target=self._guard, args=(self._publisher,), daemon=True, name="publisher")]
            for thread in self._service:
                thread.start()

    def _guard(self, target, *args):
        while True:
            try:
                return target(*args)
            except Exception:  # keep threads alive and visible instead of silently dying
                log.exception("Hintergrundfehler in %s", target.__name__)
                time.sleep(5)

    # ------------------------------------------------------------------ recording ----
    def buffer(self, channel):
        with self.lock:
            if channel not in self.buffers:
                self.buffers[channel] = (LiveBuffer(self.root / "buffer" / channel, limit=LIMIT_BYTES // 2,
                                                    disk_usage=self.adapters.disk_usage), threading.Lock())
            return self.buffers[channel]

    def _monitor(self, name):
        state = self.channels[name]
        buffer, lock = self.buffer(name)
        while self.running.is_set():
            try:
                info = self.adapters.lookup(name)
            except Exception as exc:
                state.state, state.warning = "Fehler", str(exc)[:200]
                info = None
            if not info:
                state.live, state.recording = False, False
                if state.state != "Fehler":
                    state.state = "offline"
                self._sleep(LOOKUP_SECONDS)
                continue
            state.live, state.state, state.warning = True, "live", ""
            state.category = info.get("category_name", "")
            self._session(name, state, buffer, lock, info)
        state.state, state.live, state.recording, state.chat = "gestoppt", False, False, "getrennt"

    def _sleep(self, seconds):
        self.cancel.wait(seconds)

    def _session(self, name, state, buffer, lock, info):
        with lock:
            if not buffer.has_room(time.time()):
                state.state = "pausiert"
                state.warning = "Weniger als 5 GB frei oder Pufferlimit erreicht. Speicher freigeben."
                self._sleep(LOOKUP_SECONDS)
                return
            session_id, directory = buffer.begin(name, info, self.cfg, time.time())
        capture = chat = None
        detector = SpikeDetector(self.spike_cfg)
        last_lookup = time.monotonic()
        try:
            capture = self.adapters.capture(name, directory)
            state.recording = True
            while self.running.is_set():
                now = time.time()
                if chat is None:
                    try:
                        chat = self.adapters.chat(name)
                        detector.connect(now)
                        state.chat = "verbunden (Aufwärmen)"
                    except Exception as exc:
                        state.chat, state.warning = "getrennt", str(exc)[:200]
                events = []
                if chat is not None:
                    try:
                        for at, user, sent in chat.read():
                            events += detector.message(at, user, sent)
                    except ConnectionError:
                        # Data gap: warm up again after reconnect.
                        detector.disconnect()
                        chat.close()
                        chat = None
                        state.chat = "getrennt (Neuverbindung)"
                    events += detector.tick(now)
                    if chat is not None:
                        state.chat = "verbunden" if detector.warmed else "verbunden (Aufwärmen)"
                    state.messages_10s = sum(detector.current.values())
                    if detector.history:
                        state.baseline = sorted(c for c, _ in detector.history)[len(detector.history) // 2]
                with lock:
                    for item in capture.completed():
                        buffer.add_segment(session_id, *item)
                    for event in events:
                        state.spikes += 1
                        buffer.trigger(session_id, event, self.cfg.get("reaction_delay", 6))
                    if time.monotonic() - last_lookup >= LOOKUP_SECONDS:
                        last_lookup = time.monotonic()
                        fresh = self.adapters.lookup(name)
                        if not fresh or fresh["stream_id"] != info["stream_id"]:
                            break  # stream ended or new session: never mix sessions
                        buffer.observe_category(session_id, fresh, now)
                        state.category = fresh.get("category_name", "")
                    if not buffer.has_room(now):
                        state.state = "pausiert"
                        state.warning = "Weniger als 5 GB frei oder Pufferlimit erreicht. Aufnahme pausiert."
                        break
                    self._schedule(name, buffer)
                if not capture.running:
                    state.warning = "Aufnahme unterbrochen. Neuer Versuch."
                    break
                self.cancel.wait(0.5)
        finally:
            state.recording = False
            if capture is not None:
                capture.close()
            if chat is not None:
                chat.close()
            with lock:
                for item in capture.completed() if capture is not None else []:
                    try:
                        buffer.add_segment(session_id, *item)
                    except RuntimeError:
                        break
                buffer.end(session_id)
                self._schedule(name, buffer)

    def _schedule(self, name, buffer):
        for candidate in buffer.public_candidates():
            key = candidate["id"]
            if key in self.scheduled or candidate["coverage"] == "exported":
                continue
            if candidate["coverage"] == "incomplete":
                self.scheduled.add(key)
                self.queue.skip(candidate, "Aufnahme unvollständig: Kontext fehlt.")
            elif candidate["coverage"] == "complete" and not candidate["category_pending"]:
                self.scheduled.add(key)
                self.work.put((name, key))

    # --------------------------------------------------------------------- worker ----
    def _worker(self):
        while True:
            name, key = self.work.get()
            if not self.running.is_set():
                continue
            self._process(name, key)

    def _process(self, name, key):
        buffer, lock = self.buffer(name)
        with lock:
            candidate = next((c for c in buffer.public_candidates() if c["id"] == key), None)
            segments = buffer.coverage(buffer.candidates[key]) if candidate else None
            if not segments:
                if candidate:
                    self.queue.skip(candidate, "Segmente fehlen.")
                return
            buffer.exporting.add(key)
            directory = buffer.directory(buffer.candidates[key]["session"])
        folder = self.root / "clips" / key
        folder.mkdir(parents=True, exist_ok=True)
        self.queue.begin_clip(candidate)
        self.worker_state = {"stage": "Erkennung", "detail": "Ausschnitt exportieren", "clip": key}
        try:
            source = export_segments(directory, segments, candidate["start"] - segments[0]["start"],
                                     candidate["end"] - candidate["start"], folder / "source.mp4", self.cancel)
        except Exception as exc:
            self.queue.skip(candidate, f"Export fehlgeschlagen: {exc}"[:200])
            self.queue.progress(key, "skipped", f"Export fehlgeschlagen: {exc}"[:200])
            return
        finally:
            with lock:
                buffer.exporting.discard(key)
                if key in buffer.candidates:
                    buffer.candidates[key]["coverage"] = "exported"
                    buffer.save()
        try:
            self.queue.progress(key, "analysis", "Transkript und lokale KI")
            self.worker_state = {"stage": "Analyse", "detail": "Transkript und lokale KI", "clip": key}
            ask = self.adapters.ask

            def ask_for_channel(units, anchor, cfg):
                return ask(units, anchor, cfg, channel=name)

            self.queue.progress(key, "render", "Schnitt und Prüfung")
            result = pipeline.process(candidate, source, folder, self.cfg,
                                      transcribe=self.adapters.transcribe, ask=ask_for_channel, cancel=self.cancel)
            self.queue.finish_clip(key, {**candidate, **result})
        except Exception as exc:
            log.exception("Verarbeitung fehlgeschlagen")
            self.queue.progress(key, "failed", f"Verarbeitung fehlgeschlagen: {type(exc).__name__}")
        finally:
            self.worker_state = {"stage": "bereit", "detail": "", "clip": None}

    # ------------------------------------------------------------------ publisher ----
    def _publisher(self):
        last_check = 0
        while True:
            time.sleep(1 if self.demo else 2)
            if time.monotonic() - last_check >= (10 if self.demo else REVIEW_CHECK_SECONDS):
                last_check = time.monotonic()
                self._check_reviews()
            if not (self.running.is_set() and self.cfg.get("upload_enabled")):
                continue
            enabled = {p for p in self.cfg.get("platforms_enabled", PLATFORMS)
                       if self.platform_pause[p][0] <= time.time() and self._package_ok(p) and self._account_ok(p)}
            if not enabled:
                continue
            item = self.queue.claim(self.cfg["streamers"], enabled, self.cfg["score_threshold"])
            if item:
                self._publish(item)

    def _package_ok(self, platform):
        """Post in packages (default 3 clips), then rest (default 60 minutes) per platform."""
        size = int(self.cfg.get("upload_package_size", 3))
        rest = float(self.cfg.get("upload_package_pause", 3600))
        wait = self.queue.package_wait(platform, size, rest)
        if wait > 0:
            self.platform_pause[platform] = (time.time() + wait, f"Paket mit {size} Clips gepostet – Pause.")
            return False
        return True

    def _account_ok(self, platform):
        uploader = self.adapters.uploaders.get(platform)
        if uploader is None:
            return False
        if self.platform_account[platform] is None:
            try:
                self.platform_account[platform] = uploader.account() or ""
            except Pause as exc:
                self.platform_pause[platform] = (time.time() + exc.seconds, str(exc))
                return False
            except Exception as exc:
                self.platform_pause[platform] = (time.time() + 300, f"Konto nicht lesbar: {type(exc).__name__}")
                return False
        expected = (self.cfg.get("accounts") or {}).get(platform)
        actual = self.platform_account[platform]
        if not expected or expected != actual:
            self.platform_pause[platform] = (time.time() + 30, f"Zielkonto „{actual}“ im Dashboard bestätigen.")
            return False
        return True

    def _publish(self, item):
        platform = item["platform"]
        uploader = self.adapters.uploaders[platform]
        path = self.root / "clips" / item["id"] / "final.mp4"
        meta = item["data"].get("metadata") or pipeline.metadata(item["channel"], self.cfg)
        try:
            outcome = uploader.upload(path, meta, lambda: self.queue.submitted(item))
        except Pause as exc:
            self.platform_pause[platform] = (time.time() + exc.seconds, str(exc))
            self.queue.release(item, str(exc))
            return
        except Exception as exc:
            if self.queue.was_sent(item):
                # Sent but no answer: never retried automatically.
                self.queue.finish_post(item, "unknown", detail=f"Unklarer Ausgang ({type(exc).__name__}). Bitte prüfen.")
            else:
                self.queue.finish_post(item, "failed", detail=f"Nicht gesendet: {type(exc).__name__}. Erneut versuchen möglich.")
            return
        receipt = outcome.get("receipt")
        if receipt is not None and platform == "tiktok":
            receipt = {**receipt, "account": self.platform_account.get(platform)}
        self.queue.finish_post(item, outcome["status"], url=outcome.get("url"), receipt=receipt,
                               detail=outcome.get("detail", ""))

    def _check_reviews(self):
        for row in self.queue.checkable(time.time() - (5 if self.demo else 60)):
            uploader = self.adapters.uploaders.get(row["platform"])
            if uploader is None:
                continue
            try:
                outcome = uploader.check(row["receipt"])
            except Exception:
                continue
            item = {"id": row["id"], "platform": row["platform"], "attempt": row["attempt"]}
            self.queue.finish_post(item, outcome["status"], url=outcome.get("url") or row.get("url"),
                                   receipt=outcome.get("receipt") or row["receipt"], detail=outcome.get("detail", ""))

    # ------------------------------------------------------------------ dashboard ----
    def snapshot(self):
        names = self.selected()
        clips = self.queue.snapshot()
        counts = {"erkannt": 0, "analyse": 0, "fertig": 0, "geeignet": 0, "veröffentlicht": 0}
        for clip in clips:
            counts["erkannt"] += 1
            if clip["status"] in {"analysis", "render"}:
                counts["analyse"] += 1
            if clip["status"] == "done":
                counts["fertig"] += 1
                if clip["data"].get("eligible"):
                    counts["geeignet"] += 1
            if any(p["status"] == "public" for p in clip.get("posts", {}).values()):
                counts["veröffentlicht"] += 1
        now = time.time()
        return {"running": self.running.is_set(), "demo": self.demo, "streamers": self.cfg["streamers"],
                "selected": names,
                "channels": [self.channels[n].public() if n in self.channels else Channel(n).public() for n in names],
                "worker": self.worker_state, "queued": self.work.qsize(), "counts": counts,
                "threshold": self.cfg["score_threshold"], "upload_enabled": bool(self.cfg.get("upload_enabled")),
                "platforms_enabled": list(self.cfg.get("platforms_enabled", PLATFORMS)),
                "platforms": {p: {"paused_until": self.platform_pause[p][0] if self.platform_pause[p][0] > now else None,
                                  "detail": self.platform_pause[p][1] if self.platform_pause[p][0] > now else "",
                                  "account": self.platform_account[p],
                                  "confirmed": (self.cfg.get("accounts") or {}).get(p)} for p in PLATFORMS},
                "clips": [self._public_clip(c) for c in clips]}

    def _public_clip(self, clip):
        data = clip["data"]
        folder = self.root / "clips" / clip["id"]
        edit = data.get("edit") or {}
        return {"id": clip["id"], "channel": clip["channel"], "created": clip["created"], "status": clip["status"],
                "detail": clip["detail"], "score": data.get("score"), "eligible": data.get("eligible"),
                "reason": data.get("reason"), "duration": data.get("duration"),
                "cut": [edit.get("source_start"), edit.get("source_end")] if edit else None,
                "final": (folder / "final.mp4").is_file(), "original": (folder / "original.mp4").is_file(),
                "thumb": (folder / "thumb.jpg").is_file(),
                "posts": {p: {k: v for k, v in post.items() if k in ("status", "url", "detail")}
                          for p, post in clip.get("posts", {}).items()}}

    def retry(self, clip_id, platform):
        return self.queue.retry(clip_id, platform)

    def confirm_account(self, platform):
        account = self.platform_account.get(platform)
        if not account:
            return False
        self.save_settings(accounts={**(self.cfg.get("accounts") or {}), platform: account})
        self.platform_pause[platform] = (0, "")
        return True
