"""Persistent segment inventory and candidate reservations for one live buffer."""

import json
from pathlib import Path
import re
import shutil
import tempfile
from uuid import uuid4

from .live_capture import SEGMENT_NAME


RING_SECONDS = 300
LIMIT_BYTES = 5_000_000_000
FREE_MIN_BYTES = 5_000_000_000
HEADROOM_BYTES = 128_000_000
CANDIDATE_LIMIT = 128
SESSION_ID = re.compile(r"[0-9a-f]{32}\Z")
COVERAGE_SLACK = 0.08


def _remove(path):
    """Delete a segment. Windows refuses while another process holds it open: report False."""
    try:
        path.unlink(missing_ok=True)
        return True
    except PermissionError:
        return False


class LiveBuffer:
    def __init__(self, root, *, limit=LIMIT_BYTES, free_min=FREE_MIN_BYTES, headroom=HEADROOM_BYTES,
                 disk_usage=shutil.disk_usage):
        self.root = Path(root).resolve()
        self.index = self.root / "index.json"
        self.limit = limit
        self.free_min = free_min
        self.headroom = headroom
        self.disk_usage = disk_usage
        self.sessions = {}
        self.candidates = {}
        self.active = set()
        self.exporting = set()
        if self.index.exists():
            try:
                data = json.loads(self.index.read_text(encoding="utf-8"))
                self.sessions = data["sessions"]
                self.candidates = data["candidates"]
                if data["version"] != 1 or any(not SESSION_ID.fullmatch(key) for key in self.sessions):
                    raise ValueError
                for session_id in self.sessions:
                    self.refresh(session_id)
            except (ValueError, OSError, KeyError, TypeError, AttributeError):
                raise RuntimeError("Der Live-Puffer-Index ist beschädigt. Aufnahme pausiert.") from None

    def save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.root, suffix=".tmp", mode="w",
                                         encoding="utf-8", delete=False) as temporary:
            staged = Path(temporary.name)
            try:
                json.dump({"version": 1, "sessions": self.sessions, "candidates": self.candidates}, temporary)
            except BaseException:
                temporary.close()
                staged.unlink(missing_ok=True)
                raise
        try:
            staged.replace(self.index)
        finally:
            staged.unlink(missing_ok=True)

    def directory(self, session_id):
        directory = self.root / session_id
        if not SESSION_ID.fullmatch(session_id) or directory.is_symlink():
            raise RuntimeError("Ungültiger Live-Aufnahmepfad.")
        return directory

    def begin(self, channel, info, cfg, at):
        session_id = uuid4().hex
        self.sessions[session_id] = {"channel": channel, "stream_id": info["stream_id"],
                                     "stream_started": info["stream_started"],
                                     "categories": [], "segments": [], "anchor": None, "latest": None,
                                     "required_game_id": cfg.get("required_game_id", ""),
                                     "required_game_name": cfg.get("required_game_name", "")}
        self.active.add(session_id)
        self.observe_category(session_id, info, at)
        directory = self.directory(session_id)
        directory.mkdir(parents=True, exist_ok=False)
        self.save()
        return session_id, directory

    def observe_category(self, session_id, info, at):
        session = self.sessions[session_id]
        game = info.get("category_id") or None
        categories = session["categories"]
        if categories and at <= categories[-1][0]:
            at = categories[-1][0] + 0.001
        categories.append([at, game, info.get("category_name", "")])
        self.refresh(session_id)

    def add_segment(self, session_id, name, pts_start, pts_end, received):
        session = self.sessions[session_id]
        path = self.directory(session_id) / name
        if not SEGMENT_NAME.fullmatch(name) or path.is_symlink() or not path.is_file():
            raise RuntimeError("Abgeschlossenes Live-Segment fehlt.")
        anchor = session["anchor"]
        if anchor is None:
            anchor = received - pts_end
            session["anchor"] = anchor
        start, end = anchor + pts_start, anchor + pts_end
        if session["latest"] is not None and end <= session["latest"]:
            raise RuntimeError("Die Zeitleiste der Live-Aufnahme ist unterbrochen.")
        category = next((item for item in reversed(session["categories"]) if item[0] <= start), None)
        session["segments"].append({"name": name, "start": start, "end": end,
                                    "category_id": category[1] if category else None})
        session["latest"] = end
        self.refresh(session_id)

    def end(self, session_id):
        self.active.discard(session_id)
        self.refresh(session_id)
        self.save()

    def trigger(self, session_id, evidence, delay):
        trigger = evidence["received_at"] - delay
        for candidate in reversed(list(self.candidates.values())):
            if (candidate["session"] == session_id and candidate["coverage"] in {"waiting", "complete"}
                    and candidate["id"] not in self.exporting and 0 <= trigger - candidate["last_trigger"] <= 60
                    and trigger + 30 <= candidate["start"] + 120):
                candidate["end"] = trigger + 30
                candidate["last_trigger"] = trigger
                if evidence["strength_ratio"] > candidate["chat"]["strength_ratio"]:
                    candidate["chat"] = evidence
                    candidate["trigger"] = trigger
                self.refresh(session_id)
                return candidate["id"]
        if len(self.candidates) >= CANDIDATE_LIMIT:
            retired = next((key for key, old in self.candidates.items()
                            if old["coverage"] in {"exported", "incomplete"}), None)
            if retired is None:
                return None
            del self.candidates[retired]
        key = uuid4().hex
        self.candidates[key] = {"id": key, "session": session_id, "start": trigger - 30,
                                "end": trigger + 30, "trigger": trigger, "last_trigger": trigger,
                                "coverage": "waiting", "chat": evidence,
                                "category_review": True, "category_pending": True, "category_id": None, "category_name": ""}
        self.refresh(session_id)
        return key

    def coverage(self, candidate):
        session_id = candidate["session"]
        directory = self.directory(session_id)
        needed = []
        end = candidate["start"]
        for segment in self.sessions[session_id]["segments"]:
            if segment["end"] <= candidate["start"] or segment["start"] >= candidate["end"]:
                continue
            path = directory / segment["name"]
            if segment["start"] > end + COVERAGE_SLACK or not path.is_file() or path.is_symlink():
                return None
            needed.append(segment)
            end = max(end, segment["end"])
            if end + COVERAGE_SLACK >= candidate["end"]:
                return needed
        return None

    def refresh(self, session_id):
        session = self.sessions[session_id]
        categories = session["categories"]
        for candidate in self.candidates.values():
            if candidate["session"] != session_id or candidate["coverage"] == "exported":
                continue
            start, end = candidate["start"], candidate["end"]
            if self.coverage(candidate):
                candidate["coverage"] = "complete"
            elif session_id in self.active and (session["latest"] is None or session["latest"] < end):
                candidate["coverage"] = "waiting"
            else:
                candidate["coverage"] = "incomplete"
            before = next((i for i in range(len(categories) - 1, -1, -1) if categories[i][0] <= start + COVERAGE_SLACK), None)
            after = next((i for i, category in enumerate(categories) if category[0] >= end), None)
            # Keep previously bracketed evidence when the rolling category history moves ahead.
            if before is None and candidate["category_id"]:
                continue
            candidate["category_pending"] = after is None and session_id in self.active
            bracketed = categories[before:after + 1] if before is not None and after is not None else []
            games = {item[1] for item in bracketed}
            game = next(iter(games)) if len(games) == 1 else None
            candidate["category_id"] = game
            candidate["category_name"] = bracketed[-1][2] if game else ""
            required = session["required_game_id"]
            candidate["category_review"] = not game or (bool(required or session["required_game_name"]) and game != required)

    def _reserved(self, session_id, segment):
        return any(candidate["session"] == session_id and candidate["coverage"] in {"waiting", "complete"}
                   and candidate["start"] < segment["end"] and candidate["end"] > segment["start"]
                   for candidate in self.candidates.values())

    def _delete_segment(self, session_id, segment):
        name = segment["name"]
        if not SEGMENT_NAME.fullmatch(name):
            raise RuntimeError("Ungültiger Segmentname im Live-Puffer.")
        path = self.directory(session_id) / name
        if not path.is_symlink() and not _remove(path):
            return  # still open by a recorder on Windows: keep it listed and retry on the next prune
        self.sessions[session_id]["segments"].remove(segment)

    def bytes_used(self, session_id=None):
        size = 0
        ids = [session_id] if session_id is not None else self.sessions
        for key in ids:
            directory = self.directory(key)
            if directory.is_dir():
                # Include any open file that FFmpeg has not listed as completed yet.
                for path in directory.iterdir():
                    if SEGMENT_NAME.fullmatch(path.name) and not path.is_symlink():
                        try:
                            size += path.stat().st_size
                        except FileNotFoundError:
                            continue
        return size

    def prune(self, now):
        changed = False
        keep_sessions = {item["session"] for item in self.candidates.values()}
        for key, session in list(self.sessions.items()):
            for segment in list(session["segments"]):
                if segment["end"] <= now - RING_SECONDS and not self._reserved(key, segment):
                    self._delete_segment(key, segment)
                    changed = True
            segments = session["segments"]
            first = min((s["start"] for s in segments if s["end"] > now - RING_SECONDS), default=now)
            relevant = [c["start"] for c in self.candidates.values()
                        if c["session"] == key and c["coverage"] == "waiting"]
            cutoff = min([first, *relevant])
            categories = session["categories"]
            while len(categories) > 1 and categories[1][0] < cutoff:
                del categories[0]
                changed = True
            if key not in self.active:
                directory = self.directory(key)
                names = {s["name"] for s in segments}
                for path in directory.glob("*.ts"):
                    if (SEGMENT_NAME.fullmatch(path.name) and path.name not in names and not path.is_symlink()):
                        changed = _remove(path) or changed
                if key not in keep_sessions and not segments:
                    if directory.is_dir() and not any(directory.iterdir()):
                        try:
                            directory.rmdir()
                        except OSError:
                            continue
                    del self.sessions[key]
                    changed = True
        if changed:
            self.save()

    def has_room(self, now):
        self.prune(now)
        self.root.mkdir(parents=True, exist_ok=True)
        used = self.bytes_used()
        if used + self.headroom > self.limit:
            removable = sorted((segment["end"], key, segment["name"], segment)
                               for key, session in self.sessions.items() for segment in session["segments"]
                               if not self._reserved(key, segment))
            while used + self.headroom > self.limit and removable:
                _, key, _, segment = removable.pop(0)
                self._delete_segment(key, segment)
                used = self.bytes_used()
                self.save()
        return used + self.headroom <= self.limit and self.disk_usage(self.root).free >= self.free_min + self.headroom

    def public_candidates(self):
        rows = []
        for candidate in reversed(list(self.candidates.values())):
            session = self.sessions[candidate["session"]]
            row = {key: candidate.get(key) for key in ("id", "start", "end", "trigger", "coverage", "chat",
                                                   "category_id", "category_name", "category_review", "category_pending")}
            row.update({key: session[key] for key in ("channel", "stream_id", "stream_started")})
            row.update(started_at=row["stream_started"], game_id=row["category_id"],
                       game_name=row["category_name"])
            rows.append(row)
        return rows
