"""Publish a finite snapshot of finished ClipMac videos to TikTok sequentially."""
import argparse
import fcntl
import json
import os
import re
import sqlite3
import time

from . import tiktok
from .state import RUNTIME, atomic_json


def prepare(account, should_stop=lambda: False):
    from .state import Store, settings
    cfg = settings()
    pack = None
    if cfg.get('publish_batch_size', 1) > 1:
        from .tiktok_schedule import next_pack
        pack = next_pack(Store(RUNTIME/'queue.sqlite'),tiktok.RECEIPTS,account,cfg)
        if pack['blocked']:
            raise RuntimeError('TikTok-Ergebnis eines früheren Pakets ungeklärt. Zuerst prüfen.')
        ids = pack['ids']
    else:
        with sqlite3.connect(f"file:{RUNTIME / 'queue.sqlite'}?mode=ro", uri=True) as db:
            ids = [r[0] for r in db.execute("SELECT id FROM jobs WHERE status IN ('ready','published') ORDER BY created")]
    items, skipped = [], []
    for clip_id in ids:
        if should_stop():
            raise tiktok.StopRequested("Vorbereitung gestoppt.")
        receipt = tiktok.receipt_path(account, clip_id)
        if receipt.exists():
            status = json.loads(receipt.read_text())["status"]
            if status not in ("verified", "pending_review", "cancelled_before_post"):
                raise RuntimeError(f"Ungeklärter früherer Versuch: {clip_id}. Zuerst prüfen.")
            if status != "cancelled_before_post":
                skipped.append({"clip_id": clip_id, "reason": "already_published"})
                continue
        try:
            payload = tiktok.clip_payload(clip_id)
            items.append({"clip_id": clip_id, "sha256": payload["sha256"], "caption": payload["caption"], "status": "pending"})
        except (ValueError, OSError) as exc:
            skipped.append({"clip_id": clip_id, "reason": str(exc)})
    return {"account": account, "created": time.time(), "status": "prepared", "items": items, "skipped": skipped,
            "youtube_batch_id": pack['batch_id'] if pack else None}


def studio_posts(page, account):
    page.goto("https://www.tiktok.com/tiktokstudio/content", wait_until="domcontentloaded")
    links = page.locator(f'a[href*="/@{account}/video/"]')
    links.first.wait_for(state="visible", timeout=45000)
    # Extract only visible post-row text; never cookies, storage or network credentials.
    rows = links.evaluate_all("""links => links.map(a => {
        let row = a;
        for(let n=a.parentElement; n; n=n.parentElement) {
            let count=[...n.querySelectorAll('a')].filter(x=>x.href.includes('/video/')).length;
            if(count!==1) break;
            row=n;
        }
        return {url:a.href, caption:a.innerText, row:row.innerText};
    })""")
    return {r["url"]: r for r in rows}


def match_new_post(before, after, caption, accept_review=False):
    normalized = " ".join(caption.split())
    candidates = [r for url, r in after.items() if url not in before and
                  " ".join(r["caption"].split()) == normalized and
                  ("Everyone" in r["row"].splitlines() or
                   (accept_review and "Content under review" in r["row"]))]
    # More than one new matching item is ambiguous: no invented mapping.
    return candidates[0] if len(candidates) == 1 else None


def run(plan, plan_path, should_stop=lambda: False):
    account = plan["account"]
    plan["status"] = "running"
    atomic_json(plan_path, plan)
    def pause():
        plan.update(status="paused_by_user", stopped=time.time())
        atomic_json(plan_path, plan)
        return False
    if should_stop():
        return pause()
    with tiktok.browser() as session:
        _, page = session
        for index, item in enumerate(plan["items"]):
            if should_stop():
                return pause()
            clip_id = item["clip_id"]
            if item["status"] in ("verified", "pending_review"):
                continue
            print(f"[{index + 1}/{len(plan['items'])}] {clip_id}: Vorbereitung", flush=True)
            plan["current"] = clip_id
            try:
                current = tiktok.clip_payload(clip_id)
                if current["sha256"] != item["sha256"] or current["caption"] != item["caption"]:
                    raise ValueError("Datei oder Beschreibung seit Auftragsstart geändert.")
                before = studio_posts(page, account)
                item.update(status="uploading", started=time.time(), previous_urls=list(before))
                atomic_json(plan_path, plan)
                upload_error = None
                try:
                    tiktok.publish(account, clip_id, session=session, should_stop=should_stop)
                except tiktok.StopRequested:
                    item["status"] = "pending"
                    return pause()
                except Exception as exc:
                    upload_error = type(exc).__name__
                match = None
                for attempt in range(3):
                    after = studio_posts(page, account)
                    match = match_new_post(before, after, item["caption"], accept_review=True)
                    if match:
                        break
                    if attempt < 2:
                        page.wait_for_timeout(5000)
                if not match:
                    raise RuntimeError("Kein eindeutig zuordenbarer öffentlicher Beitrag gefunden" + (f" ({upload_error})" if upload_error else ""))
                receipt = tiktok.receipt_path(account, clip_id)
                record = json.loads(receipt.read_text())
                status = "pending_review" if "Content under review" in match["row"] else "verified"
                record.update(status=status, video_url=match["url"], verified_at=time.time(),
                              verification="new_studio_row_matching_caption", studio_row=match["row"])
                atomic_json(receipt, record)
                item.update(status=status, video_url=match["url"], finished=time.time())
                atomic_json(plan_path, plan)
                label = "TikTok-Prüfung läuft" if status == "pending_review" else "Öffentlich bestätigt"
                print(f"[{index + 1}/{len(plan['items'])}] {label}: {match['url']}", flush=True)
            except Exception as exc:
                item.update(status="needs_review", error=str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__)
                plan.update(status="needs_review", stopped=time.time())
                atomic_json(plan_path, plan)
                with __import__('contextlib').suppress(Exception):
                    page.screenshot(path=str(plan_path.with_suffix(".png")))
                print(f"Angehalten: {item['error']}", flush=True)
                return False
    if should_stop():
        return pause()
    plan.update(status="complete", finished=time.time())
    atomic_json(plan_path, plan)
    print("Auftrag vollständig hochgeladen und in TikTok Studio zugeordnet; einzelne Beiträge können noch in Prüfung sein.", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    account = tiktok.account_name(args.account)
    tiktok.RECEIPTS.mkdir(parents=True, exist_ok=True)
    with (tiktok.RECEIPTS / "pilot.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = prepare(account)
        plan_path = tiktok.RECEIPTS / f"batch-{time.time_ns()}.json"
        atomic_json(plan_path, plan)
        print(f"{len(plan['items'])} Videos vorbereitet; {len(plan['skipped'])} übersprungen. Auftrag: {plan_path}", flush=True)
        if not args.prepare_only and not run(plan, plan_path):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
