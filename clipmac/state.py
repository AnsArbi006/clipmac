from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .environment import ROOT, RUNTIME, DEVELOPMENT
DEFAULTS = {
    "streamers": ["papaplatte", "rohat", "zarbex", "trymacs"],
    "lookback_hours": 7,
    "top_per_streamer": 5,
    "selection_scope": "per_streamer",
    "required_game_id": "",
    "required_game_name": "",
    "poll_minutes": 15,
    "publish_interval_minutes": 0,
    "publish_batch_size": 1,
    "publish_batch_interval_minutes": 60,
    "language": "de",
    "whisper_model": "small",
    "ollama_model": "qwen2.5:3b",
    "highlight_recommendation_threshold": 60,
    "silence_db": -38,
    "silence_min_seconds": 0.8,
    "silence_padding_seconds": 0.15,
    "facecam": True,
    "facecam_share": 1 / 3,
    "facecam_crops": {},
    "publish_enabled": True,
    "channel_id": "",
    "channel_title": "",
}


def atomic_json(path: Path, value, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        if private:
            os.fchmod(f.fileno(), 0o600)
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def settings():
    path = RUNTIME / "settings.json"
    value = {**DEFAULTS, **(json.loads(path.read_text()) if path.exists() else {})}
    if DEVELOPMENT:
        value.update(publish_enabled=False, channel_id="", channel_title="")
    return value


def save_settings(changes):
    result = settings()
    permitted = {"streamers", "top_per_streamer", "publish_interval_minutes", "facecam", "facecam_share", "publish_enabled", "selection_scope", "publish_batch_size", "publish_batch_interval_minutes", "highlight_recommendation_threshold"}
    for key in permitted & changes.keys():
        result[key] = changes[key]
    if not isinstance(result["streamers"], list) or not 1 <= len(result["streamers"]) <= 30:
        raise ValueError("Bitte 1–30 Twitch-Kanäle angeben.")
    result["streamers"] = list(dict.fromkeys(str(s).lower().strip() for s in result["streamers"]))
    if any(not re.fullmatch(r"[a-z0-9_]{3,25}", s) for s in result["streamers"]):
        raise ValueError("Bitte Twitch-Kanalnamen ohne URL oder Leerzeichen eingeben.")
    if result["selection_scope"] not in {"global", "per_streamer"}:
        raise ValueError("Ungültige Top-Auswahl.")
    result["top_per_streamer"] = int(result["top_per_streamer"])
    result["publish_interval_minutes"] = int(result["publish_interval_minutes"])
    result["publish_batch_size"] = int(result["publish_batch_size"])
    result["publish_batch_interval_minutes"] = int(result["publish_batch_interval_minutes"])
    if not 1 <= result["publish_batch_size"] <= 20 or not 1 <= result["publish_batch_interval_minutes"] <= 1440:
        raise ValueError("Paketgröße muss 1–20 sein, Paketpause 1–1440 Minuten.")
    if not 1 <= result["top_per_streamer"] <= 20:
        raise ValueError("Pro Kanal sind 1–20 Top-Clips möglich.")
    if not 0 <= result["publish_interval_minutes"] <= 1440:
        raise ValueError("Der Veröffentlichungsabstand muss zwischen 0 und 1440 Minuten liegen (0 = sofort).")
    for key in ("facecam", "publish_enabled"):
        if not isinstance(result[key], bool):
            raise ValueError(f"{key}: ungültiger Wert")
    if result["facecam_share"] not in (1 / 3, 0.5):
        raise ValueError("Facecam-Anteil muss ein Drittel oder die Hälfte sein.")
    threshold = result["highlight_recommendation_threshold"]
    if type(threshold) is not int or not 0 <= threshold <= 100:
        raise ValueError("Empfehlungsschwelle als ganze Zahl von 0 bis 100 angeben.")
    atomic_json(RUNTIME / "settings.json", result)
    return result


def secrets():
    if DEVELOPMENT:
        return {}
    p = RUNTIME / "credentials" / "twitch.json"
    return json.loads(p.read_text()) if p.exists() else {}


class Store:
    def __init__(self, path=None):
        self.path = Path(path or RUNTIME / "queue.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, clip TEXT NOT NULL, status TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL,
                    error TEXT NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT '{}',
                    youtube_id TEXT NOT NULL DEFAULT '', published REAL,
                    attempts INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, message TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS deleted_clips (
                    id TEXT PRIMARY KEY, clip TEXT NOT NULL, youtube_id TEXT NOT NULL,
                    deleted_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS publish_batches (
                    id INTEGER PRIMARY KEY, created REAL NOT NULL, finished REAL
                );
                CREATE TABLE IF NOT EXISTS publish_batch_items (
                    batch_id INTEGER NOT NULL, position INTEGER NOT NULL,
                    clip_id TEXT NOT NULL UNIQUE, streamer TEXT NOT NULL,
                    PRIMARY KEY(batch_id, position)
                );
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY, clip_id TEXT NOT NULL, created REAL NOT NULL,
                    note TEXT NOT NULL, position REAL, status TEXT NOT NULL DEFAULT 'open',
                    evidence_state TEXT NOT NULL DEFAULT 'pending',
                    snapshot TEXT NOT NULL, analysis TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '', resolution TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS reports_clip ON reports(clip_id,status);
                CREATE TABLE IF NOT EXISTS ratings (
                    id INTEGER PRIMARY KEY, clip_id TEXT NOT NULL, created REAL NOT NULL,
                    value TEXT, revision TEXT NOT NULL, snapshot TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ratings_clip ON ratings(clip_id,id);
                CREATE TABLE IF NOT EXISTS performance_samples (
                    id INTEGER PRIMARY KEY, clip_id TEXT NOT NULL, youtube_id TEXT NOT NULL,
                    observed_at REAL NOT NULL, published_at REAL NOT NULL, age_seconds REAL NOT NULL,
                    views INTEGER, likes INTEGER, comments INTEGER, availability TEXT NOT NULL,
                    revision TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS performance_clip ON performance_samples(clip_id,id);
                CREATE TABLE IF NOT EXISTS performance_checkpoints (
                    clip_id TEXT NOT NULL, hour INTEGER NOT NULL, state TEXT NOT NULL,
                    sample_id INTEGER, PRIMARY KEY(clip_id,hour)
                );
                CREATE TABLE IF NOT EXISTS performance_sync (
                    clip_id TEXT PRIMARY KEY, next_check REAL NOT NULL, error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS learning_contexts (
                    clip_id TEXT NOT NULL, revision TEXT NOT NULL, captured_at REAL NOT NULL,
                    context TEXT NOT NULL, PRIMARY KEY(clip_id,revision)
                );
                CREATE TABLE IF NOT EXISTS learning_notes (
                    id TEXT PRIMARY KEY, created REAL NOT NULL, topic TEXT NOT NULL,
                    note TEXT NOT NULL, source TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS youtube_metadata_observations (
                    sample_id INTEGER PRIMARY KEY, metadata TEXT NOT NULL
                );
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def log(self, message):
        print(message, flush=True)
        with self.db() as db:
            db.execute("INSERT INTO events(at,message) VALUES (?,?)", (time.time(), str(message)))

    def rows(self, status=None):
        with self.db() as db:
            query = "SELECT * FROM jobs" + (" WHERE status=?" if status else "") + " ORDER BY created"
            rows = db.execute(query, (status,) if status else ()).fetchall()
        return [{**dict(r), "clip": json.loads(r["clip"]), "result": json.loads(r["result"])} for r in rows]

    def get(self, clip_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (clip_id,)).fetchone()
        return {**dict(row), "clip": json.loads(row["clip"]), "result": json.loads(row["result"])} if row else None

    def add(self, clip):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", clip["id"]):
            raise ValueError("Ungültige Clip-ID")
        now = time.time()
        with self.db() as db:
            return db.execute("INSERT OR IGNORE INTO jobs(id,clip,status,created,updated) SELECT ?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM deleted_clips WHERE id=?)",
                              (clip["id"], json.dumps(clip), "queued", now, now, clip["id"])).rowcount == 1

    def known_clips(self):
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT clip FROM jobs UNION ALL SELECT clip FROM deleted_clips")]

    def remove_confirmed_deleted(self, clip_id, youtube_id):
        """Only call after the corresponding remote deletion has been verified."""
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (clip_id,)).fetchone()
            if not row:
                return
            if row["youtube_id"] != youtube_id or row["status"] in {"uploading", "editing", "downloading"}:
                raise ValueError("Löschidentität oder Jobstatus stimmt nicht überein.")
            db.execute("INSERT OR REPLACE INTO deleted_clips VALUES (?,?,?,?)", (clip_id, row["clip"], youtube_id, time.time()))
            db.execute("DELETE FROM youtube_metadata_observations WHERE sample_id IN (SELECT id FROM performance_samples WHERE clip_id=?)", (clip_id,))
            for table in ("reports", "ratings", "performance_samples", "performance_checkpoints", "performance_sync", "learning_contexts"):
                db.execute(f"DELETE FROM {table} WHERE clip_id=?", (clip_id,))
            db.execute("DELETE FROM jobs WHERE id=?", (clip_id,))

    def update(self, clip_id, status, **fields):
        if not fields.keys() <= {"error", "result", "youtube_id", "published", "attempts"}:
            raise ValueError("Unbekanntes Statusfeld")
        if "result" in fields:
            fields["result"] = json.dumps(fields["result"], ensure_ascii=False)
        fields.update(status=status, updated=time.time())
        with self.db() as db:
            db.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in fields) + " WHERE id=?",
                       (*fields.values(), clip_id))

    def transition(self, clip_id, expected, target):
        with self.db() as db:
            if target == "uploading":
                # Check the hold in the same SQL statement as the upload reservation.
                return db.execute("""UPDATE jobs SET status=?, updated=? WHERE id=? AND status=?
                    AND NOT EXISTS (SELECT 1 FROM reports WHERE clip_id=jobs.id AND status='open')""",
                    (target, time.time(), clip_id, expected)).rowcount == 1
            return db.execute("UPDATE jobs SET status=?, updated=? WHERE id=? AND status=?",
                              (target, time.time(), clip_id, expected)).rowcount == 1

    def recover(self):
        # Interrupted encoding is safe to repeat; an uncertain upload is not.
        with self.db() as db:
            db.execute("UPDATE jobs SET status='queued' WHERE status IN ('downloading','editing')")
            db.execute("UPDATE jobs SET status='upload_unknown', error=? WHERE status='uploading'",
                       ("Upload wurde unterbrochen. In YouTube Studio prüfen; kein automatischer Neuversuch.",))

    def last_publish(self):
        with self.db() as db:
            return db.execute("SELECT COALESCE(MAX(published),0) FROM jobs").fetchone()[0]

    def next_publish(self, now, interval, cfg=None):
        due = self.last_publish() + interval * 60
        if cfg and cfg.get("publish_batch_size", 1) > 1:
            from .scheduling import next_batch_time
            due = max(due, next_batch_time(self, cfg))
        return max(now, due, self.upload_blocked_until())

    def upload_blocked_until(self):
        with self.db() as db:
            row = db.execute("SELECT value FROM meta WHERE key='upload_blocked_until'").fetchone()
        return float(row[0]) if row else 0

    def defer_uploads(self, until):
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('upload_blocked_until',?)", (str(until),))

    def ready_to_publish(self, now, interval, cfg=None):
        # Any ambiguous upload blocks the whole publishing queue, avoiding bursts/duplicates.
        if self.rows("upload_unknown") or self.rows("uploading"):
            return None
        if now < self.next_publish(now, interval, cfg):
            return None
        if cfg and cfg.get("publish_batch_size", 1) > 1:
            from .scheduling import batch_job
            return batch_job(self, now, cfg)
        held = {r["clip_id"] for r in self.report_rows() if r["status"] == "open"}
        ready = [r for r in self.rows("ready") if r["id"] not in held]
        return ready[0] if ready else None

    def add_report(self, clip_id, note, position, cfg):
        import math
        import uuid
        if not isinstance(note, str) or not 3 <= len(note.strip()) <= 3000:
            raise ValueError("Bitte beschreibe das Problem in 3 bis 3000 Zeichen.")
        if position is not None:
            try:
                position = float(position)
            except (ValueError, TypeError):
                raise ValueError("Die Zeitangabe muss eine Sekundenzahl sein.")
            if not math.isfinite(position) or position < 0:
                raise ValueError("Bitte eine gültige Zeit ab 0 Sekunden angeben.")
        report_id = uuid.uuid4().hex
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (clip_id,)).fetchone()
            if not row:
                raise ValueError("Dieser Clip wurde nicht gefunden.")
            result = json.loads(row["result"])
            duration = result.get("render", {}).get("duration")
            if position is not None and duration and position > duration:
                raise ValueError("Die Zeitangabe liegt hinter dem Videoende.")
            snapshot = {"clip": json.loads(row["clip"]), "result": result,
                        "job_status": row["status"], "youtube_id": row["youtube_id"],
                        "settings": {k: cfg.get(k) for k in ("facecam", "facecam_share", "facecam_crops", "silence_db", "silence_min_seconds", "silence_padding_seconds", "whisper_model", "ollama_model")}}
            db.execute("INSERT INTO reports(id,clip_id,created,note,position,snapshot) VALUES (?,?,?,?,?,?)",
                       (report_id, clip_id, time.time(), note.strip(), position, json.dumps(snapshot, ensure_ascii=False)))
        return report_id

    def report_rows(self):
        with self.db() as db:
            rows = db.execute("SELECT * FROM reports ORDER BY created DESC").fetchall()
        return [{**dict(r), "snapshot": json.loads(r["snapshot"]), "analysis": json.loads(r["analysis"])} for r in rows]

    def report_evidence(self, report_id, analysis=None, error=""):
        with self.db() as db:
            db.execute("UPDATE reports SET evidence_state=?,analysis=?,error=? WHERE id=?",
                       ("failed" if error else "ready", json.dumps(analysis or {}, ensure_ascii=False), error, report_id))

    def withdraw_report(self, report_id):
        with self.db() as db:
            changed = db.execute("UPDATE reports SET status='withdrawn' WHERE id=? AND status='open'", (report_id,)).rowcount
        if not changed:
            raise ValueError("Diese Meldung ist nicht mehr offen.")

    def event_rows(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 50")]

    def rate(self, clip_id, value):
        from .learning import render_revision
        if value not in ("good", "medium", "bad", None):
            raise ValueError("Bitte Gut, Mittel oder Schlecht auswählen.")
        job = self.get(clip_id)
        if not job or not job["result"].get("file") or not Path(job["result"]["file"]).is_file():
            raise ValueError("Du kannst bewerten, sobald die fertige Vorschau verfügbar ist.")
        revision = render_revision(job)
        snapshot = {"clip": job["clip"], "result": job["result"], "youtube_id": job["youtube_id"],
                    "label_source": "user_subjective", "revision": revision}
        with self.db() as db:
            previous = db.execute("SELECT value,revision FROM ratings WHERE clip_id=? ORDER BY id DESC LIMIT 1", (clip_id,)).fetchone()
            if previous and previous["value"] == value and previous["revision"] == revision:
                return
            db.execute("INSERT INTO ratings(clip_id,created,value,revision,snapshot) VALUES (?,?,?,?,?)",
                       (clip_id, time.time(), value, revision, json.dumps(snapshot, ensure_ascii=False)))

    def rating_rows(self, history=False):
        with self.db() as db:
            query = "SELECT * FROM ratings" if history else "SELECT * FROM ratings WHERE id IN (SELECT MAX(id) FROM ratings GROUP BY clip_id)"
            rows = db.execute(query + " ORDER BY id").fetchall()
        return [{**dict(r), "snapshot": json.loads(r["snapshot"])} for r in rows]

    def performance_rows(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM performance_samples ORDER BY id")]

    def learning_context_rows(self):
        with self.db() as db:
            return [{**dict(r), "context": json.loads(r["context"])}
                    for r in db.execute("SELECT * FROM learning_contexts ORDER BY captured_at,clip_id")]

    def add_learning_note(self, note_id, topic, note):
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO learning_notes VALUES (?,?,?,?,?)",
                       (note_id, time.time(), topic, note, "user_feedback"))

    def learning_note_rows(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM learning_notes ORDER BY created,id")]

    def youtube_metadata_rows(self):
        with self.db() as db:
            return [{"sample_id": r["sample_id"], "metadata": json.loads(r["metadata"])}
                    for r in db.execute("SELECT * FROM youtube_metadata_observations ORDER BY sample_id")]

    def capture_learning_context(self, job):
        from .learning import render_revision, video_context
        if not job.get("result", {}).get("file"):
            return
        revision = render_revision(job)
        with self.db() as db:
            if db.execute("SELECT 1 FROM learning_contexts WHERE clip_id=? AND revision=?", (job["id"], revision)).fetchone():
                return
        context = video_context(job)
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO learning_contexts VALUES (?,?,?,?)",
                       (job["id"], revision, time.time(), json.dumps(context, ensure_ascii=False)))

    def checkpoint_rows(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM performance_checkpoints ORDER BY hour")]

    def performance_sync_rows(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM performance_sync")]

    def defer_performance(self, clip_id, until, error=""):
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO performance_sync(clip_id,next_check,error) VALUES (?,?,?)", (clip_id, until, error))

    def record_performance(self, job, values, observed_at, published_at):
        from .learning import CHECKPOINT_HOURS, WINDOW_SECONDS, render_revision
        self.capture_learning_context(job)
        age = max(0, observed_at - published_at)
        availability = values.get("availability", "unavailable")
        with self.db() as db:
            cursor = db.execute("""INSERT INTO performance_samples
                (clip_id,youtube_id,observed_at,published_at,age_seconds,views,likes,comments,availability,revision)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", (job["id"], job["youtube_id"], observed_at, published_at, age,
                values.get("views"), values.get("likes"), values.get("comments"), availability, render_revision(job)))
            sample_id = cursor.lastrowid
            if "youtube_metadata" in values:
                db.execute("INSERT INTO youtube_metadata_observations VALUES (?,?)",
                           (sample_id, json.dumps(values["youtube_metadata"], ensure_ascii=False)))
            for hour in CHECKPOINT_HOURS:
                if age < hour * 3600:
                    continue
                recorded = availability == "public" and values.get("views") is not None and age <= hour * 3600 + WINDOW_SECONDS
                # While inside the observation window, a temporary missing response remains retryable.
                if not recorded and age <= hour * 3600 + WINDOW_SECONDS:
                    continue
                db.execute("INSERT OR IGNORE INTO performance_checkpoints(clip_id,hour,state,sample_id) VALUES (?,?,?,?)",
                           (job["id"], hour, "recorded" if recorded else "missed", sample_id if recorded else None))
            future = [published_at + h * 3600 for h in CHECKPOINT_HOURS if age < h * 3600]
            retry_window = any(h * 3600 <= age <= h * 3600 + WINDOW_SECONDS for h in CHECKPOINT_HOURS) and (availability != "public" or values.get("views") is None)
            next_check = observed_at + 300 if retry_window else min(future, default=observed_at + 365 * 86400)
            db.execute("INSERT OR REPLACE INTO performance_sync(clip_id,next_check,error) VALUES (?,?,?)",
                       (job["id"], next_check, "" if availability == "public" else "Video oder öffentliche Statistik momentan nicht verfügbar."))


def overlaps(a, b):
    if not a.get("video_id") or a.get("video_id") != b.get("video_id"):
        return False
    if a.get("vod_offset") is None or b.get("vod_offset") is None:
        return False
    sa, sb = float(a["vod_offset"]), float(b["vod_offset"])
    da, db = float(a["duration"]), float(b["duration"])
    intersection = max(0, min(sa + da, sb + db) - max(sa, sb))
    return intersection >= 0.5 * min(da, db)


def select_clips(clips, existing, limit, started, ended):
    chosen = []
    from datetime import datetime
    known = {c["id"] for c in existing}
    for c in sorted(clips, key=lambda c: (-int(c.get("view_count", 0)), c["id"])):
        when = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
        if c["id"] in known or not started <= when <= ended or not 5 <= float(c.get("duration", 0)) <= 180:
            continue
        if any(overlaps(c, other) for other in existing + chosen):
            continue
        chosen.append(c)
        if len(chosen) >= limit:
            break
    return chosen
