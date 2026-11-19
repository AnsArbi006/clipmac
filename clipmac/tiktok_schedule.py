"""Mirror the already published YouTube packs, without draining the old backlog."""
import json
import time
from datetime import datetime, timezone

from .content_policy import rejection_reason

ACCEPTED = {'verified', 'pending_review'}


def next_pack(store, folder, account, cfg, now=None):
    now = time.time() if now is None else now
    with store.db() as db:
        rows = db.execute('''SELECT i.batch_id,i.position,i.clip_id,j.status,j.clip
            FROM publish_batch_items i LEFT JOIN jobs j ON j.id=i.clip_id
            ORDER BY i.batch_id,i.position''').fetchall()
    packs = {}
    for row in rows:
        packs.setdefault(row['batch_id'], []).append(row)
    held = {r['clip_id'] for r in store.report_rows() if r['status']=='open'}
    bad = {r['clip_id'] for r in store.rating_rows() if r.get('value')=='bad'}
    previous_end = 0
    gap = cfg.get('publish_batch_interval_minutes',60)*60
    for batch_id, jobs in packs.items():
        remaining, accepted_times = [], []
        unfinished = any(j['status'] in {'queued','downloading','editing','ready','uploading','upload_unknown'} for j in jobs)
        for j in jobs:
            receipt = folder/account/(j['clip_id']+'.json')
            r = json.loads(receipt.read_text()) if receipt.exists() else {}
            if r.get('status') in ACCEPTED:
                accepted_times.append(r.get('verified_at',r.get('updated',r.get('started',0))))
                continue
            if r and r.get('status') != 'cancelled_before_post':
                return {'ids':[], 'next_at':0, 'batch_id':batch_id, 'blocked':True}
            if j['status']=='published' and j['clip_id'] not in held|bad:
                if not rejection_reason(json.loads(j['clip']),cfg,datetime.fromtimestamp(now,timezone.utc)):
                    remaining.append(j['clip_id'])
        if unfinished:
            return {'ids':[], 'next_at':previous_end+gap if previous_end else 0, 'batch_id':batch_id, 'blocked':False}
        if remaining:
            due = previous_end+gap if previous_end else 0
            return {'ids':remaining[:cfg.get('publish_batch_size',5)] if now>=due else [],
                    'next_at':due,'batch_id':batch_id,'blocked':False}
        if accepted_times:
            previous_end=max(previous_end,max(accepted_times))
    return {'ids':[], 'next_at':previous_end+gap if previous_end else 0,'batch_id':None,'blocked':False}
