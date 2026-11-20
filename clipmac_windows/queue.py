"""Local work and platform receipts for the Windows application."""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from .config import PLATFORMS


class Queue:
    def __init__(self, path):
        self.path = path
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS clips (
                    id TEXT PRIMARY KEY, channel TEXT NOT NULL, created REAL NOT NULL,
                    status TEXT NOT NULL, detail TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS posts (
                    clip_id TEXT NOT NULL REFERENCES clips(id), platform TEXT NOT NULL,
                    status TEXT NOT NULL, attempt TEXT, sent INTEGER NOT NULL DEFAULT 0,
                    url TEXT, receipt TEXT, detail TEXT NOT NULL DEFAULT '', updated REAL NOT NULL,
                    PRIMARY KEY (clip_id, platform));
            ''')
            db.execute("UPDATE clips SET status='interrupted', detail='Analyse unterbrochen.' WHERE status IN ('analysis', 'render', 'qa')")
            db.execute("""UPDATE posts SET status=CASE WHEN sent=1 THEN 'unknown' ELSE 'waiting' END,
                       detail=CASE WHEN sent=1 THEN 'Versand prüfen. Der Auftrag bleibt gesperrt.' ELSE 'Wartet nach Neustart.' END
                       WHERE status='uploading'""")
            # Additive migration: when a post was handed to the platform (package pacing).
            if 'sent_at' not in {row[1] for row in db.execute('PRAGMA table_info(posts)')}:
                db.execute('ALTER TABLE posts ADD COLUMN sent_at REAL')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def begin_clip(self, candidate):
        with self.db() as db:
            return db.execute('INSERT OR IGNORE INTO clips VALUES (?,?,?,?,?,?)',
                              (candidate['id'], candidate['channel'], time.time(), 'analysis',
                               'Live-Ausschnitt wird exportiert.', json.dumps(candidate))).rowcount == 1

    def progress(self, clip_id, stage, detail):
        with self.db() as db:
            db.execute('UPDATE clips SET status=?, detail=? WHERE id=?', (stage, detail, clip_id))

    def finish_clip(self, clip_id, result):
        with self.db() as db:
            db.execute('UPDATE clips SET status=?, detail=?, data=? WHERE id=?', ('done', result.get('reason', ''),
                       json.dumps(result, ensure_ascii=False, allow_nan=False), clip_id))
            if result.get('eligible') is True:
                db.executemany('INSERT OR IGNORE INTO posts(clip_id,platform,status,updated) VALUES (?,?,?,?)',
                               [(clip_id, platform, 'waiting', time.time()) for platform in PLATFORMS])

    def _clip(self, row):
        return {**dict(row), 'data': json.loads(row['data'])}

    def clip(self, clip_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM clips WHERE id=?', (clip_id,)).fetchone()
            return self._clip(row) if row else None

    def snapshot(self, limit=100):
        with self.db() as db:
            rows = [self._clip(row) for row in db.execute('SELECT * FROM clips ORDER BY created DESC LIMIT ?', (limit,))]
            for row in rows:
                posts = db.execute('SELECT platform,status,url,detail FROM posts WHERE clip_id=?', (row['id'],))
                row['posts'] = {post['platform']: dict(post) for post in posts}
            return rows

    def claim(self, channels, enabled, threshold):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute("""SELECT c.*, p.platform FROM posts p JOIN clips c ON c.id=p.clip_id
                                 WHERE p.status='waiting' ORDER BY c.created, CASE p.platform WHEN 'tiktok' THEN 0 ELSE 1 END""")
            for raw in rows:
                row = self._clip(raw)
                clip_id, platform = row['id'], row['platform']
                if row['channel'] not in channels or platform not in enabled or row['data'].get('score', -1) < threshold:
                    continue
                if platform == 'youtube' and 'tiktok' in enabled:
                    tiktok = db.execute("SELECT status FROM posts WHERE clip_id=? AND platform='tiktok'", (clip_id,)).fetchone()
                    if tiktok and tiktok['status'] in {'waiting', 'uploading'}:
                        continue
                attempt = uuid.uuid4().hex
                db.execute("""UPDATE posts SET status='uploading', attempt=?, sent=0, detail='', updated=?
                              WHERE clip_id=? AND platform=?""", (attempt, time.time(), clip_id, platform))
                return {**row, 'attempt': attempt}
        return None

    def submitted(self, item):
        with self.db() as db:
            now = time.time()
            changed = db.execute("""UPDATE posts SET sent=1, sent_at=?, updated=? WHERE clip_id=? AND platform=?
                                    AND attempt=? AND status='uploading' AND sent=0""",
                                 (now, now, item['id'], item['platform'], item['attempt'])).rowcount
        if changed != 1:
            raise RuntimeError('Uploadversuch wurde bereits versandt oder ist nicht mehr aktiv.')

    def finish_post(self, item, status, *, url=None, receipt=None, detail=''):
        with self.db() as db:
            db.execute("""UPDATE posts SET status=?, url=?, receipt=?, detail=?, updated=?
                          WHERE clip_id=? AND platform=? AND attempt=? AND status IN ('uploading','review','unknown')""",
                       (status, url, json.dumps(receipt) if receipt else None, detail, time.time(),
                        item['id'], item['platform'], item['attempt']))

    def checkable(self, cutoff):
        with self.db() as db:
            rows = db.execute("""SELECT clip_id AS id,platform,attempt,receipt,url FROM posts
                                 WHERE status='review' AND receipt IS NOT NULL AND updated<? ORDER BY updated LIMIT 10""", (cutoff,))
            return [{**dict(row), 'receipt': json.loads(row['receipt'])} for row in rows]

    def retry(self, clip_id, platform):
        with self.db() as db:
            # A definite rejection may be retried manually; an unclear ("unknown") send never.
            return bool(db.execute("""UPDATE posts SET status='waiting', detail='', attempt=NULL, sent=0
                                   WHERE clip_id=? AND platform=?
                                   AND (status='failed' OR (status='paused' AND sent=0))""",
                                   (clip_id, platform)).rowcount)

    def count(self):
        with self.db() as db:
            return dict(db.execute('SELECT status,count(*) FROM posts GROUP BY status').fetchall())

    def release(self, item, detail):
        """Pause before sending: the attempt never left this PC, so it may run again later."""
        with self.db() as db:
            db.execute("""UPDATE posts SET status='waiting', attempt=NULL, detail=?, updated=?
                          WHERE clip_id=? AND platform=? AND attempt=? AND status='uploading' AND sent=0""",
                       (detail, time.time(), item['id'], item['platform'], item['attempt']))

    def skip(self, candidate, reason):
        """Record a candidate that could not be processed, so the dashboard explains the gap."""
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO clips VALUES (?,?,?,?,?,?)',
                       (candidate['id'], candidate['channel'], time.time(), 'skipped', reason,
                        json.dumps({**candidate, 'eligible': False, 'reason': reason})))

    def was_sent(self, item):
        with self.db() as db:
            row = db.execute('SELECT sent FROM posts WHERE clip_id=? AND platform=? AND attempt=?',
                             (item['id'], item['platform'], item['attempt'])).fetchone()
            return bool(row and row['sent'])

    def package_wait(self, platform, size, pause, now=None):
        """Seconds until the next post may start: packages of `size` posts, then `pause` seconds rest."""
        now = time.time() if now is None else now
        with self.db() as db:
            times = [row[0] for row in db.execute(
                'SELECT sent_at FROM posts WHERE platform=? AND sent_at IS NOT NULL ORDER BY sent_at DESC LIMIT 50',
                (platform,))]
        package = []
        for sent_at in times:  # newest first; a gap of at least `pause` begins a new package
            if package and package[-1] - sent_at >= pause:
                break
            package.append(sent_at)
        if len(package) < size:
            return 0.0
        return max(0.0, package[0] + pause - now)
