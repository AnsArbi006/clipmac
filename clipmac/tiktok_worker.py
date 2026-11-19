"""Local worker owned by the dashboard; no Codex or external AI calls."""
import argparse
import fcntl
import json
import os
import signal
import time

from . import tiktok, tiktok_batch
from .state import atomic_json
from .tiktok_service import read_json, recover_before_post, ACCEPTED


def check_receipts(account, should_stop):
    folder = tiktok.RECEIPTS
    with tiktok.browser() as (_, page):
        if should_stop():
            raise tiktok.StopRequested()
        rows = tiktok_batch.studio_posts(page, account)
        plans = [read_json(p) for p in sorted(folder.glob("batch-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)]
        changed = 0
        for path in (folder / account).glob("*.json"):
            if should_stop():
                raise tiktok.StopRequested()
            if ".attempt-" in path.name:
                continue
            record = read_json(path)
            if record.get("status") == "cancelled_before_post":
                continue
            match = rows.get(record.get("video_url"))
            if not match and record.get("status") not in ACCEPTED:
                item = next((i for plan in plans for i in plan.get("items", []) if i["clip_id"] == path.stem and "previous_urls" in i), None)
                if item:
                    match = tiktok_batch.match_new_post(item["previous_urls"], rows, record["caption"], accept_review=True)
            if match and " ".join(match["caption"].split()) == " ".join(record["caption"].split()):
                status = "pending_review" if "Content under review" in match["row"] else ("verified" if "Everyone" in match["row"].splitlines() else "visibility_review")
                record.update(status=status, video_url=match["url"], verified_at=time.time(),
                              verification="studio_status_check", studio_row=match["row"])
                atomic_json(path, record)
                changed += 1
    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--action", choices=("upload", "check", "connect"), required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args()
    import re
    if not re.fullmatch(r"[a-f0-9]{32}", args.run_id):
        raise ValueError("Ungültiger Auftrag")
    account = tiktok.account_name(args.account)
    os.umask(0o077)
    folder = tiktok.RECEIPTS
    folder.mkdir(parents=True, exist_ok=True)
    stop_file = folder / "stop.request"
    should_stop = lambda: stop_file.exists() or os.getppid() != args.parent_pid
    def stop_signal(*_):
        stop_file.touch(mode=0o600)
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    state = {"run_id": args.run_id, "action": args.action, "account": account, "started": time.time()}
    def update(phase, message):
        state.update(phase=phase, message=message, updated=time.time())
        atomic_json(folder / "dashboard.json", state)
    try:
        with (folder / "pilot.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if should_stop():
                raise tiktok.StopRequested()
            recover_before_post(folder, account)
            if args.action == "connect":
                update("connecting", "Im geöffneten TikTok-Fenster anmelden und das eigene Profil öffnen.")
                tiktok.connect(account, should_stop=should_stop)
                update("complete", "TikTok-Anmeldung bestätigt.")
            elif args.action == "check":
                update("checking", "Prüfe die zuletzt sichtbaren Beiträge in TikTok Studio …")
                count = check_receipts(account, should_stop)
                update("complete", f"{count} sichtbare Beiträge abgeglichen. Ältere Einträge behalten ihren letzten bekannten Status.")
            else:
                update("preparing", "Prüfe fertige Clips, Fehlermeldungen und bereits erfolgte Uploads …")
                plan = tiktok_batch.prepare(account, should_stop=should_stop)
                plan_path = folder / f"batch-dashboard-{args.run_id}.json"
                atomic_json(plan_path, plan)
                if not plan["items"]:
                    update("complete", "Keine weiteren lokal verfügbaren, freigegebenen Clips vorhanden.")
                    return
                update("uploading", "Videos werden nacheinander hochgeladen. Du kannst diese Seite schließen.")
                result = tiktok_batch.run(plan, plan_path, should_stop=should_stop)
                if result:
                    update("complete", "Alle Videos dieses Auftrags sind hochgeladen. TikTok kann einzelne Beiträge noch prüfen.")
                elif plan.get("status") == "paused_by_user":
                    update("paused", "Gestoppt. Noch nicht abgeschickte Videos bleiben für den nächsten Start bereit.")
                else:
                    update("error", "Upload angehalten. Ergebnis oder TikTok-Hinweis prüfen; es wird nicht automatisch erneut gepostet.")
    except tiktok.StopRequested:
        update("paused", "Gestoppt. Es wird kein weiterer Post gestartet.")
    except Exception as exc:
        message = str(exc)[:250] if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        update("error", "TikTok angehalten: " + message + " Bei Anmeldung oder CAPTCHA „Anmeldung erneuern“ verwenden und die Abfrage im geöffneten Fenster abschließen.")


if __name__ == "__main__":
    main()
