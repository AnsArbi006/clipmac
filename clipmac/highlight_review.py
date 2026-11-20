"""Review cut versions locally and admit approved live cuts to the existing queue."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .content_policy import rejection_reason
from .environment import RUNTIME, require_live
from .highlight_score import DEFAULT_THRESHOLD, VERSION as SCORE_VERSION, finite, score_highlight
from .state import atomic_json, overlaps

_DIGEST = re.compile(r"[a-f0-9]{64}")
_ARTIFACTS = ("source.mp4", "transcript.json", "captions.ass", "captions.srt",
              "caption-layout.json", "layout-timeline.json", "metadata.json")


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest(value):
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _source_time(candidate):
    start, end = candidate.get("start"), candidate.get("end")
    if not finite(start) or not finite(end) or not 0 <= start < end:
        raise ValueError("Ungültiger Schnitt-Zeitraum.")
    if candidate.get("kind") == "live":
        capture = candidate.get("live_context") or {}
        origin, tail = capture.get("start"), capture.get("end")
        if not finite(origin) or not finite(tail) or origin < 0 or origin + end > tail + .001:
            raise ValueError("Aufnahmezeit des Live-Schnitts ist nicht belegt.")
        return origin + start, origin + end
    return start, end


def candidate_key(candidate):
    kind, source = candidate.get("kind"), candidate.get("source_id")
    media = candidate.get("source_media_sha256")
    if (kind not in {"live", "vod", "local"} or not isinstance(source, (str, int)) or
            isinstance(source, bool) or not str(source) or not _digest(media)):
        raise ValueError("Für den Schnitt fehlt ein belegter Medienursprung.")
    start, end = _source_time(candidate)
    material = [1, kind, str(source), round(start * 1_000_000), round(end * 1_000_000), media]
    return "hl-" + hashlib.sha256(json.dumps(material, separators=(",", ":")).encode()).hexdigest()


def _revision(candidate):
    revision = candidate.get("render_revision")
    if candidate.get("preview_ready") is not True or not _digest(revision):
        raise ValueError("Bitte zuerst die Vorschau dieses Schnitts erzeugen.")
    return revision


def _publication_reason(clip, cfg, now):
    if clip.get("streamer_login") not in cfg["streamers"]:
        return "Streamer nicht mehr freigegeben."
    source = clip.get("source_interval")
    start, end = source if isinstance(source, (tuple, list)) and len(source) == 2 else (None, None)
    lookback = min(7, cfg.get("lookback_hours", 7)) * 3600
    if not finite(start) or not finite(end) or not now - lookback <= start < end <= now:
        return "Live-Schnitt liegt außerhalb des aktuellen Zeitfensters."
    if not clip.get("game_id"):
        return "Spielkategorie nicht belegt."
    return rejection_reason(clip, cfg, datetime.fromtimestamp(now, timezone.utc))


def _conflicts(clip, existing):
    if clip["id"] == existing.get("id") or clip["render_revision"] == existing.get("render_revision"):
        return True
    if clip["stream_id"] == existing.get("stream_id"):
        other = existing.get("source_interval")
        if isinstance(other, (tuple, list)) and len(other) == 2 and all(finite(x) for x in other):
            a, b = clip["source_interval"]
            c, d = other
            if a < d and c < b:
                return True
    return overlaps(clip, existing)


def _known(db, exclude=""):
    rows = db.execute("SELECT clip FROM jobs WHERE id != ? UNION ALL SELECT clip FROM deleted_clips", (exclude,))
    return (json.loads(row[0]) for row in rows)


def queued_highlight_rejection(job, store, cfg, *, runtime=RUNTIME, now=None):
    """Recheck source eligibility, collisions and approved render before upload reservation."""
    with store.db() as db:
        return highlight_rejection_in_db(job, db, cfg, runtime=runtime, now=now)


def highlight_rejection_in_db(job, db, cfg, *, runtime=RUNTIME, now=None):
    clip = job["clip"]
    if clip.get("source_type") != "live_highlight":
        return ""
    reason = _publication_reason(clip, cfg, time.time() if now is None else now)
    if reason:
        return reason
    if any(_conflicts(clip, other) for other in _known(db, exclude=job["id"])):
        return "Ein überlappender oder identischer Ausschnitt ist bereits bekannt."
    expected = Path(runtime) / "clips" / job["id"] / "final.mp4"
    try:
        if (Path(job["result"]["file"]) != expected.resolve() or expected.is_symlink() or
                not expected.resolve().is_relative_to(Path(runtime).resolve()) or
                _sha256(expected) != clip["render_revision"]):
            return "Die Videodatei weicht von der freigegebenen Fassung ab."
    except (KeyError, OSError, TypeError):
        return "Die freigegebene Videofassung konnte nicht geprüft werden."
    return ""


class HighlightReviews:
    def __init__(self, store, *, runtime=RUNTIME):
        self.store, self.runtime = store, Path(runtime).resolve()
        with self.store.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS highlight_reviews_v1 (
                    sequence INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL,
                    candidate_key TEXT NOT NULL, revision TEXT NOT NULL, created REAL NOT NULL,
                    kind TEXT NOT NULL, value TEXT, note TEXT, position REAL,
                    status TEXT NOT NULL DEFAULT 'open'
                );
                CREATE INDEX IF NOT EXISTS highlight_reviews_v1_candidate
                    ON highlight_reviews_v1(candidate_key, revision, kind, sequence);
                CREATE TABLE IF NOT EXISTS highlight_approvals_v1 (
                    candidate_key TEXT PRIMARY KEY, revision TEXT NOT NULL,
                    clip_id TEXT NOT NULL, approved_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS highlight_scores_v1 (
                    candidate_key TEXT NOT NULL, fingerprint TEXT NOT NULL, created REAL NOT NULL,
                    score TEXT NOT NULL, PRIMARY KEY(candidate_key, fingerprint)
                );
            """)

    def snapshot(self, candidate):
        key, revision = candidate_key(candidate), candidate.get("render_revision")
        with self.store.db() as db:
            rating = db.execute("""SELECT value FROM highlight_reviews_v1 WHERE candidate_key=?
                AND revision=? AND kind='rating' ORDER BY sequence DESC LIMIT 1""", (key, revision)).fetchone()
            reports = db.execute("""SELECT h.id, h.note, h.position, COALESCE(r.status,h.status) status, h.created
                FROM highlight_reviews_v1 h LEFT JOIN reports r ON r.id=h.id
                WHERE h.candidate_key=? AND h.revision=? AND h.kind='report' ORDER BY h.sequence DESC""", (key, revision))
            approved = db.execute("SELECT clip_id FROM highlight_approvals_v1 WHERE candidate_key=?", (key,)).fetchone()
            return {"candidate_key": key, "render_revision": revision, "rating": rating[0] if rating else None,
                    "reports": [dict(row) for row in reports], "promoted_clip_id": approved[0] if approved else None}

    def score(self, candidate, threshold=DEFAULT_THRESHOLD):
        value = score_highlight(candidate, threshold)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        key, fingerprint = candidate_key(candidate), hashlib.sha256(encoded.encode()).hexdigest()
        with self.store.db() as db:
            if not db.execute("SELECT 1 FROM highlight_scores_v1 WHERE candidate_key=? AND fingerprint=?",
                              (key, fingerprint)).fetchone():
                db.execute("INSERT OR IGNORE INTO highlight_scores_v1 VALUES (?,?,?,?)",
                           (key, fingerprint, time.time(), encoded))
        return value

    def rate(self, candidate, value):
        if value not in (None, "good", "medium", "bad"):
            raise ValueError("Bitte Gut, Mittel oder Schlecht auswählen.")
        key, revision = candidate_key(candidate), _revision(candidate)
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("""SELECT value FROM highlight_reviews_v1 WHERE candidate_key=?
                AND revision=? AND kind='rating' ORDER BY sequence DESC LIMIT 1""", (key, revision)).fetchone()
            if previous is None or previous[0] != value:
                db.execute("""INSERT INTO highlight_reviews_v1(id,candidate_key,revision,created,kind,value)
                    VALUES (?,?,?,?,'rating',?)""", (uuid.uuid4().hex, key, revision, time.time(), value))
        return self.snapshot(candidate)

    def report(self, candidate, note, position=None):
        if not isinstance(note, str) or not 3 <= len(note.strip()) <= 3000:
            raise ValueError("Bitte beschreibe das Problem in 3 bis 3000 Zeichen.")
        key, revision = candidate_key(candidate), _revision(candidate)
        duration = (candidate.get("result") or {}).get("render", {}).get("duration")
        if position is not None and (not finite(position) or position < 0 or
                                     not finite(duration) or position > duration):
            raise ValueError("Bitte eine Sekunde innerhalb der Vorschau angeben.")
        report_id, created = uuid.uuid4().hex, time.time()
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""INSERT INTO highlight_reviews_v1(id,candidate_key,revision,created,kind,note,position)
                VALUES (?,?,?,?,'report',?,?)""", (report_id, key, revision, created, note.strip(), position))
            # Preserve the existing transactional upload hold after admission to the queue.
            job = db.execute("""SELECT j.* FROM jobs j JOIN highlight_approvals_v1 a ON j.id=a.clip_id
                WHERE a.candidate_key=? AND a.revision=?""", (key, revision)).fetchone()
            if job:
                snapshot = {"clip": json.loads(job["clip"]), "result": json.loads(job["result"]),
                            "job_status": job["status"], "youtube_id": job["youtube_id"], "settings": {}}
                db.execute("INSERT INTO reports(id,clip_id,created,note,position,snapshot) VALUES (?,?,?,?,?,?)",
                           (report_id, job["id"], created, note.strip(), position, json.dumps(snapshot, ensure_ascii=False)))
        return report_id

    def withdraw(self, candidate, report_id):
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("""UPDATE highlight_reviews_v1 SET status='withdrawn' WHERE id=?
                AND candidate_key=? AND kind='report' AND status='open'""", (report_id, candidate_key(candidate))).rowcount
            if not changed:
                raise ValueError("Diese Meldung ist nicht mehr offen.")
            db.execute("UPDATE reports SET status='withdrawn' WHERE id=? AND status='open'", (report_id,))

    def promote(self, candidate, cfg, *, now=None):
        require_live("Freigabe für Uploadpaket")
        if candidate.get("kind") != "live":
            raise ValueError("Nur Highlights aus einer aktuellen Live-Aufnahme dürfen in die Paketqueue.")
        now = time.time() if now is None else now
        key, revision = candidate_key(candidate), _revision(candidate)
        capture, channel = candidate.get("live_context") or {}, candidate.get("channel")
        start, end = _source_time(candidate)
        stream, started_at = capture.get("stream_id"), capture.get("stream_started", capture.get("started_at"))
        category_id = capture.get("category_id") or capture.get("game_id")
        if (not isinstance(stream, str) or not stream.isdecimal() or stream != str(candidate.get("source_id")) or
                not isinstance(channel, str) or not re.fullmatch(r"[a-z0-9_]{3,25}", channel) or
                channel != capture.get("channel") or capture.get("coverage") not in {"complete", "exported"} or
                capture.get("category_review") is not False or not category_id or
                not finite(started_at) or not 0 < started_at <= start or not 5 <= candidate["end"] - candidate["start"] <= 120):
            raise ValueError("Aufnahme, Stream und Kategorie müssen vollständig belegt sein.")
        if candidate.get("technical_errors") or candidate.get("technical_blocked"):
            raise ValueError("Technische Fehler müssen vor der Freigabe geklärt werden.")
        result = candidate.get("result") or {}
        source = Path(result.get("file") or "").resolve()
        metadata = result.get("metadata") or {}
        if (not source.is_relative_to(self.runtime) or source.name != "final.mp4" or not source.is_file() or
                not all(isinstance(metadata.get(k), str) and metadata[k].strip() for k in ("title", "description")) or
                not isinstance(metadata.get("tags"), list)):
            raise ValueError("Vorschau oder Veröffentlichungsdaten fehlen.")
        vod = capture.get("vod_id")
        origin_offset = capture.get("vod_offset")
        vod_offset = origin_offset + candidate["start"] if finite(origin_offset) and origin_offset >= 0 else None
        verified_vod = isinstance(vod, str) and vod.isdecimal() and vod_offset is not None
        clip = {"id": key, "source_type": "live_highlight", "stream_id": stream, "streamer_login": channel,
                "broadcaster_name": channel, "created_at": datetime.fromtimestamp(start, timezone.utc).isoformat(),
                "game_id": str(category_id), "game_name": cfg.get("required_game_name", ""),
                "title": metadata["title"], "duration": end - start, "source_interval": [start, end],
                "video_id": vod if verified_vod else "", "vod_offset": vod_offset if verified_vod else None,
                "source_vod_id": vod, "vod_alignment": "verified" if verified_vod else "unknown",
                "media_sha256": candidate["source_media_sha256"], "render_revision": revision}
        reason = _publication_reason(clip, cfg, now)
        if reason:
            raise ValueError(reason)
        clips = self.runtime / "clips"
        clips.mkdir(parents=True, exist_ok=True)
        if clips.is_symlink():
            raise ValueError("Der Zielordner für Clips ist kein lokaler ClipMac-Ordner.")
        target = clips / key
        result = {**result, "file": str(target / "final.mp4")}
        manifest = {"schema_version": 1, "clip": clip, "approved_at": now,
                    "model": candidate.get("model"), "prompt_version": candidate.get("prompt_version"),
                    "score_version": SCORE_VERSION, "metadata": metadata}
        with tempfile.TemporaryDirectory(prefix=".promotion-", dir=clips) as temporary:
            # A child directory can be renamed safely while its temporary parent owns cleanup.
            stage = Path(temporary) / "clip"
            stage.mkdir()
            shutil.copy2(source, stage / "final.mp4")
            if _sha256(stage / "final.mp4") != revision:
                raise ValueError("Die Vorschau hat sich seit ihrer Erstellung geändert.")
            for name in _ARTIFACTS:
                artifact = source.parent / name
                if artifact.is_file() and not artifact.is_symlink():
                    shutil.copy2(artifact, stage / name)
            atomic_json(stage / "result.json", result)
            atomic_json(stage / "highlight-approval.json", manifest)
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                if any(_conflicts(clip, other) for other in _known(db)):
                    raise ValueError("Ein überlappender oder identischer Ausschnitt ist bereits bekannt.")
                if db.execute("SELECT 1 FROM highlight_approvals_v1 WHERE candidate_key=?", (key,)).fetchone():
                    raise ValueError("Dieser Schnitt wurde bereits freigegeben.")
                if db.execute("""SELECT 1 FROM highlight_reviews_v1 WHERE candidate_key=? AND revision=?
                    AND kind='report' AND status='open'""", (key, revision)).fetchone():
                    raise ValueError("Bitte kläre zuerst die offenen Fehlermeldungen zu dieser Fassung.")
                rating = db.execute("""SELECT value FROM highlight_reviews_v1 WHERE candidate_key=?
                    AND revision=? AND kind='rating' ORDER BY sequence DESC LIMIT 1""", (key, revision)).fetchone()
                if rating and rating[0] == "bad":
                    raise ValueError("Eine als schlecht bewertete Fassung kann nicht freigegeben werden.")
                if target.exists() or target.is_symlink():
                    # A process crash can leave a complete directory without a DB row.
                    paths = [target / name for name in ("highlight-approval.json", "result.json", "final.mp4")]
                    if target.is_symlink() or any(not path.is_file() or path.is_symlink() for path in paths):
                        raise ValueError("Der Zielordner enthält bereits eine andere Fassung.")
                    prior = json.loads(paths[0].read_text(encoding="utf-8"))
                    prior_result = json.loads(paths[1].read_text(encoding="utf-8"))
                    if (prior.get("clip") != clip or prior_result != result or _sha256(paths[2]) != revision):
                        raise ValueError("Der Zielordner enthält bereits eine andere Fassung.")
                else:
                    stage.rename(target)
                db.execute("INSERT INTO jobs(id,clip,status,created,updated,result) VALUES (?,?,'ready',?,?,?)",
                           (key, json.dumps(clip, ensure_ascii=False), now, now, json.dumps(result, ensure_ascii=False)))
                db.execute("INSERT INTO highlight_approvals_v1 VALUES (?,?,?,?)", (key, revision, key, now))
        return key
