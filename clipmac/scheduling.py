"""Persistent upload packs; one streamer per turn, with a rotating fifth slot."""
import json
from datetime import datetime, timezone

from .content_policy import rejection_reason

PENDING = {"queued", "downloading", "editing", "ready", "uploading", "upload_unknown"}


def _latest(db):
    batch = db.execute("SELECT * FROM publish_batches ORDER BY id DESC LIMIT 1").fetchone()
    if not batch:
        return None, []
    jobs = db.execute("""SELECT j.*, i.streamer, i.position FROM publish_batch_items i
        LEFT JOIN jobs j ON j.id=i.clip_id WHERE i.batch_id=? ORDER BY i.position""", (batch["id"],)).fetchall()
    return batch, jobs


def _due(db, cfg):
    batch, jobs = _latest(db)
    gap = cfg["publish_batch_interval_minutes"] * 60
    if not batch:
        last = db.execute("SELECT COALESCE(MAX(published),0) FROM jobs").fetchone()[0]
        return last + gap if last else 0
    if batch["finished"] is None and any(j["status"] in PENDING for j in jobs):
        return 0
    end = batch["finished"] or max([batch["created"]] + [j["published"] or j["updated"] or 0 for j in jobs])
    return end + gap


def next_batch_time(store, cfg):
    with store.db() as db:
        return _due(db, cfg)


def batch_job(store, now, cfg):
    """Seal a pack before uploading. Its order and wait survive process restarts."""
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE")
        if now < _due(db, cfg):
            return None
        batch, jobs = _latest(db)
        pending = [j for j in jobs if j["status"] in PENDING] if batch and batch["finished"] is None else []
        if not pending:
            if batch and batch["finished"] is None:
                end = max([batch["created"]] + [j["published"] or j["updated"] or 0 for j in jobs])
                db.execute("UPDATE publish_batches SET finished=? WHERE id=?", (end, batch["id"]))
            candidates = db.execute("""SELECT * FROM jobs WHERE status IN ('queued','downloading','editing','ready')
                AND NOT EXISTS (SELECT 1 FROM publish_batch_items WHERE clip_id=jobs.id)
                AND NOT EXISTS (SELECT 1 FROM reports WHERE clip_id=jobs.id AND status='open')""").fetchall()
            channels = cfg["streamers"]
            groups = {s: [] for s in channels}
            for row in candidates:
                clip = json.loads(row["clip"])
                login = clip.get("streamer_login", "").lower()
                if login in groups and not rejection_reason(clip, cfg, datetime.fromtimestamp(now, timezone.utc)):
                    groups[login].append((row, clip))
            for group in groups.values():
                group.sort(key=lambda pair: (-int(pair[1].get("view_count", 0)), pair[0]["created"], pair[0]["id"]))
            saved = db.execute("SELECT value FROM meta WHERE key='publish_streamer_cursor'").fetchone()
            cursor = int(saved[0]) % len(channels) if saved else 0
            chosen = []
            while len(chosen) < cfg["publish_batch_size"] and any(groups.values()):
                login = channels[cursor]
                cursor = (cursor + 1) % len(channels)
                if groups[login]:
                    chosen.append((groups[login].pop(0)[0], login))
            if not chosen:
                return None
            batch_id = db.execute("INSERT INTO publish_batches(created) VALUES (?)", (now,)).lastrowid
            db.executemany("INSERT INTO publish_batch_items VALUES (?,?,?,?)",
                           [(batch_id, i, row["id"], login) for i, (row, login) in enumerate(chosen)])
            db.execute("INSERT OR REPLACE INTO meta VALUES ('publish_streamer_cursor',?)", (str(cursor),))
            pending = [row for row, _ in chosen]
        first = pending[0]
        if first["status"] != "ready" or db.execute("SELECT 1 FROM reports WHERE clip_id=? AND status='open'", (first["id"],)).fetchone():
            return None
        return {**dict(first), "clip": json.loads(first["clip"]), "result": json.loads(first["result"])}


def batch_snapshot(store, cfg):
    if cfg.get("publish_batch_size", 1) <= 1:
        return None
    with store.db() as db:
        batch, jobs = _latest(db)
        return {"size": cfg["publish_batch_size"], "pause_minutes": cfg["publish_batch_interval_minutes"],
                "next_batch_at": _due(db, cfg), "batch_id": batch["id"] if batch else None,
                "items": [{"id": j["id"], "streamer": j["streamer"], "status": j["status"]} for j in jobs]}
