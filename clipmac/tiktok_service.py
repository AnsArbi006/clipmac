"""Local dashboard controller. Does not import browser/ML dependencies."""
import fcntl
import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .state import ROOT, RUNTIME, atomic_json
from .environment import DEVELOPMENT, require_live

ACCEPTED = {"verified", "pending_review"}
ACTIVE = {"starting", "preparing", "uploading", "checking", "connecting"}


def read_json(path, default=None):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {} if default is None else default


def worker_busy(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "pilot.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True


def recover_before_post(folder, account):
    """Only recover records proving that the guarded Post call was never entered."""
    for path in (folder / account).glob("*.json"):
        if ".attempt-" in path.name:
            continue
        record = read_json(path)
        if record.get("stage") == "preparing_form" and record.get("status") in {"posting", "upload_unknown"}:
            record.update(status="cancelled_before_post", recovered_at=time.time(),
                          recovery="Post guard was never entered; no submission started")
            atomic_json(path, record)


class TikTokController:
    def __init__(self, store, folder=None, command=None):
        self.store = store
        self.folder = Path(folder or RUNTIME / "tiktok")
        self.command = command or [str(ROOT / ".venv-tiktok/bin/python"), "-m", "clipmac.tiktok_worker"]
        self.mutex = threading.RLock()
        self.process = None
        self.shutdown = threading.Event()

    def launch(self):
        if DEVELOPMENT:
            return
        threading.Thread(target=self._auto_loop, daemon=True).start()

    def auto_enabled(self):
        return read_json(self.folder/'automatic.json').get('enabled') is True

    def _set_auto(self, enabled):
        atomic_json(self.folder/'automatic.json', {'enabled':enabled})

    def _auto_loop(self):
        while not self.shutdown.wait(15):
            with self.mutex:
                if not self.auto_enabled() or self.running():
                    continue
                try:
                    state=read_json(self.state_file)
                    if state.get('phase') in {'error','interrupted'}:
                        self._set_auto(False)
                        continue
                    from .state import settings
                    from .tiktok_schedule import next_pack
                    pack=next_pack(self.store,self.folder,self.account(),settings())
                    if pack['blocked']:
                        self._set_auto(False)
                    elif pack['ids']:
                        self.start('upload', automatic=True)
                except Exception:
                    self._set_auto(False)
                    atomic_json(self.state_file,{'phase':'error','message':'TikTok-Automatik angehalten. Lokalen Status prüfen.'})

    @property
    def state_file(self):
        return self.folder / "dashboard.json"

    @property
    def stop_file(self):
        return self.folder / "stop.request"

    def account(self):
        value = read_json(self.folder / "account.json").get("account", "")
        return value if re.fullmatch(r"[a-z0-9_.]{2,24}", value) else ""

    def running(self):
        return bool(self.process is not None and self.process.poll() is None) or worker_busy(self.folder)

    def start(self, action="upload", automatic=False):
        require_live("TikTok-Auftrag")
        if action not in {"upload", "check", "connect"}:
            raise ValueError("Unbekannte TikTok-Aktion.")
        with self.mutex:
            if self.running():
                raise ValueError("Ein TikTok-Lauf ist bereits aktiv.")
            account = self.account()
            if not account:
                raise ValueError("TikTok wurde noch nicht eingerichtet.")
            if not Path(self.command[0]).is_file():
                raise ValueError("Die lokale TikTok-Umgebung fehlt.")
            recover_before_post(self.folder, account)
            if action == "upload" and self.snapshot()["needs_review"]:
                raise ValueError("Ein Upload-Ergebnis ist unklar. Zuerst „Status prüfen“ verwenden.")
            from .state import settings
            if action == 'upload' and settings().get('publish_batch_size',1)>1:
                from .tiktok_schedule import next_pack
                pack=next_pack(self.store,self.folder,account,settings())
                if pack['blocked']:
                    raise ValueError('Ein TikTok-Paket hat ein ungeklärtes Ergebnis. Zuerst prüfen.')
                self._set_auto(True)
                if not pack['ids']:
                    atomic_json(self.state_file,{'phase':'waiting','action':'upload',
                                'message':'Automatik wartet auf das nächste veröffentlichte YouTube-Paket und die Stundenpause.'})
                    return
            self.stop_file.unlink(missing_ok=True)
            run_id = uuid.uuid4().hex
            state = {"run_id": run_id, "account": account, "phase": "starting", "action": action,
                     "started": time.time(), "message": "TikTok wird gestartet …"}
            atomic_json(self.state_file, state)
            try:
                with (self.folder / "worker.log").open("ab") as log:
                    self.process = subprocess.Popen(
                        [*self.command, "--run-id", run_id, "--account", account, "--action", action,
                         "--parent-pid", str(os.getpid())], cwd=ROOT, stdin=subprocess.DEVNULL,
                        stdout=log, stderr=log, start_new_session=True)
            except Exception:
                atomic_json(self.state_file, {**state, "phase": "error", "message": "TikTok-Prozess konnte nicht starten."})
                raise RuntimeError("TikTok-Prozess konnte nicht starten.") from None

    def stop(self):
        with self.mutex:
            self._set_auto(False)
            self.folder.mkdir(parents=True, exist_ok=True)
            self.stop_file.touch(mode=0o600)

    def snapshot(self):
        with self.mutex:
            running = self.running()
            account = self.account()
            if account and not running:
                recover_before_post(self.folder, account)
            state = read_json(self.state_file)
            receipts = {}
            for path in (self.folder / account).glob("*.json") if account else []:
                if ".attempt-" not in path.name:
                    receipts[path.stem] = read_json(path)
            jobs = self.store.rows()
            reports = {r["clip_id"] for r in self.store.report_rows() if r["status"] == "open"}
            ratings = {r["clip_id"]: r.get("value") for r in self.store.rating_rows()}
            ready = 0
            unavailable = 0
            from .state import settings
            from .content_policy import rejection_reason
            policy = settings()
            for job in jobs:
                receipt = receipts.get(job["id"], {})
                if receipt and receipt.get("status") != "cancelled_before_post":
                    continue
                if job["status"] not in {"ready", "published"} or job["id"] in reports or ratings.get(job["id"]) == "bad":
                    continue
                if rejection_reason(job["clip"], policy):
                    continue
                path = Path(job["result"].get("file", ""))
                if path.is_file() and not (getattr(path.stat(), "st_flags", 0) & 0x40000000):
                    ready += 1
                else:
                    unavailable += 1
            needs_review = sum(r.get("status") not in ACCEPTED | {"cancelled_before_post"} for r in receipts.values())
            phase = state.get("phase", "idle")
            if not running and phase in ACTIVE:
                phase = "interrupted"
            if running and self.stop_file.exists():
                phase = "stopping"
            if running and not state:
                phase = "external"
            automatic = self.auto_enabled()
            next_at = 0
            if automatic and not running and phase not in {'error','interrupted'}:
                from .tiktok_schedule import next_pack
                pack=next_pack(self.store,self.folder,account,policy)
                next_at=pack['next_at']
                phase='waiting'
            plans = sorted(self.folder.glob("batch-*.json"))
            run_id = state.get("run_id", "")
            plan_path = self.folder / f"batch-dashboard-{run_id}.json" if re.fullmatch(r"[a-f0-9]{32}", run_id) else None
            plan = read_json(plan_path) if plan_path and plan_path.exists() else (read_json(max(plans, key=lambda p: p.stat().st_mtime)) if plans else {})
            if running and state.get("action") == "upload" and plan_path and not plan_path.exists():
                plan = {}
            items = plan.get("items", [])
            completed = sum(i["status"] in ACCEPTED for i in items)
            job_map = {j["id"]: j for j in jobs}
            current = job_map.get(plan.get("current"), {}) if running and state.get("action") == "upload" and plan_path and plan_path.exists() else {}
            titles = {j["id"]: j["result"].get("metadata", {}).get("title") or j["clip"].get("title", j["id"]) for j in jobs}
            recent = []
            for clip_id, r in sorted(receipts.items(), key=lambda pair: pair[1].get("started", 0), reverse=True)[:8]:
                url = r.get("video_url", "")
                if not re.fullmatch(rf"https://www\.tiktok\.com/@{re.escape(account)}/video/[0-9]+", url):
                    url = ""
                recent.append({"clip_id": clip_id, "title": titles.get(clip_id, clip_id), "status": r.get("status"), "url": url})
            return {"account": account, "running": running, "automatic": automatic, "next_at":next_at, "phase": phase, "action": state.get("action"),
                    "message": state.get("message", ""), "ready": ready, "unavailable": unavailable,
                    "public": sum(r.get("status") == "verified" for r in receipts.values()),
                    "pending_review": sum(r.get("status") == "pending_review" for r in receipts.values()),
                    "needs_review": needs_review, "total": len(items), "completed": completed,
                    "skipped": len(plan.get("skipped", [])),
                    "current_title": current.get("result", {}).get("metadata", {}).get("title", ""),
                    "recent": recent, "can_start": bool(account and not automatic and not running and not needs_review
                        and (ready or policy.get('publish_batch_size',1)>1))}
