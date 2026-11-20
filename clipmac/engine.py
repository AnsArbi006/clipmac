import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .state import RUNTIME, Store, secrets, select_clips, settings
from . import media, publisher
from .environment import require_live


class Engine:
    def __init__(self, store=None):
        self.store = store or Store()
        self.store.recover()
        for job in self.store.rows("upload_unknown"):
            receipt = RUNTIME / "clips" / job["id"] / "youtube_receipt.json"
            if receipt.is_file():
                saved = json.loads(receipt.read_text())
                self.store.update(job["id"], saved.get("status", "published"), youtube_id=saved["video_id"], published=saved["published"], error="")
        self.active = threading.Event()
        self.shutdown = threading.Event()
        self.last_scan = 0
        self.scan_requested = threading.Event()
        self.stage = "Pausiert"
        self.publish_stage = ""
        self.lock = threading.Lock()
        self.auth_lock = threading.Lock()

    def launch(self):
        threading.Thread(target=self._process_loop, daemon=True).start()
        threading.Thread(target=self._publish_loop, daemon=True).start()
        threading.Thread(target=self._feedback_loop, daemon=True).start()
        threading.Thread(target=self._performance_loop, daemon=True).start()

    def _performance_loop(self):
        from .learning import collect_performance
        while not self.shutdown.is_set():
            cfg = settings()
            for job in self.store.rows():
                if job["result"].get("file"):
                    self.store.capture_learning_context(job)
            schedule = {r["clip_id"]: r for r in self.store.performance_sync_rows()}
            due = [j for j in self.store.rows("published") if j["youtube_id"] and j["published"]
                   and schedule.get(j["id"], {}).get("next_check", 0) <= time.time()]
            if cfg["channel_id"] and due:
                try:
                    # Serialize credential refresh with uploads and account connection.
                    with self.auth_lock:
                        service = publisher.service_for_channel(cfg["channel_id"])
                        collect_performance(self.store, service, cfg["channel_id"], time.time())
                except Exception:
                    for job in due:
                        self.store.defer_performance(job["id"], time.time() + 900,
                            "YouTube-Zahlen nicht erreichbar. Verbindung wird in 15 Minuten erneut geprüft.")
            self.shutdown.wait(60)

    def report_problem(self, clip_id, note, position=None):
        report_id = self.store.add_report(clip_id, note, position, settings())
        self.store.log(f"Problem gemeldet: {clip_id}. Prüffall wird lokal vorbereitet.")
        return report_id

    def _feedback_loop(self):
        from .feedback import prepare_case
        while not self.shutdown.is_set():
            for report in self.store.report_rows():
                if report["evidence_state"] != "pending":
                    continue
                job = self.store.get(report["clip_id"])
                if job and job["status"] in {"downloading", "editing"}:
                    continue
                try:
                    analysis = prepare_case(report, RUNTIME)
                    self.store.report_evidence(report["id"], analysis)
                except Exception as exc:
                    self.store.report_evidence(report["id"], error=str(exc)[:500])
            self.shutdown.wait(2)

    def start(self):
        require_live("Produktive Automatik")
        creds = secrets()
        if not creds.get("client_id") or not creds.get("client_secret"):
            raise ValueError("Bitte zuerst den Twitch-Zugang eintragen.")
        self.hold_ineligible()
        self.active.set()
        self.scan_requested.set()
        self.store.log("Automatik gestartet. Clips werden lokal vorbereitet; Upload nur mit verbundenem YouTube-Kanal.")

    def pause(self):
        self.active.clear()
        self.store.log("Automatik pausiert. Ein bereits laufender Schnitt oder Upload wird noch abgeschlossen.")

    def discover(self, top_per_streamer=None):
        require_live("Twitch-Abfrage")
        from twitch_api import TwitchApiClient
        cfg, creds = settings(), secrets()
        limit = cfg["top_per_streamer"] if top_per_streamer is None else top_per_streamer
        if not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("Pro Kanal sind 1–20 Top-Clips möglich.")
        client = TwitchApiClient(creds["client_id"], creds["client_secret"])
        broadcasters = client.resolve_broadcasters(cfg["streamers"])
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=cfg["lookback_hours"])
        from .content_policy import NO_FACECAM, ranked_pool
        # Clips without a facecam do not count toward the top N; the next clip moves up.
        no_camera = {j["id"] for j in self.store.rows("policy_blocked") if j["error"] == NO_FACECAM}
        all_clips, summary = [], {}
        for login in cfg["streamers"]:
            if not self.active.is_set():
                break
            if login not in broadcasters:
                self.store.log(f"Twitch-Kanal nicht gefunden: {login}")
                continue
            clips = client.get_clips_for_broadcaster(broadcasters[login], start, end)
            for clip in clips:
                clip["streamer_login"] = login
            all_clips.extend(c for c in clips if c["id"] not in no_camera)
            summary[login] = {"found": len(clips)}
        # Rank only matching categories, across channels when global is selected.
        # Keep already-known clips in this top pool so repeated polls do not drain
        # the rest of the window one batch at a time.
        pool = ranked_pool(all_clips, cfg, limit, end)
        known = self.store.known_clips()
        selected = select_clips(pool, known, max(1, len(pool)), start, end)
        game_ids = sorted({c.get("game_id") for c in selected if c.get("game_id")})
        games = {}
        if game_ids:
            games = {g["id"]: g["name"] for g in client._helix_get("/games", [("id", g) for g in game_ids]).get("data", [])}
        added = 0
        for clip in selected:
            clip["game_name"] = games.get(clip.get("game_id"), "")
            added += self.store.add(clip)
        for login in summary:
            summary[login]["matching"] = sum(c["streamer_login"] == login and
                (not cfg.get("required_game_id") or c.get("game_id") == cfg["required_game_id"])
                for c in all_clips)
            summary[login]["top_ids"] = [c["id"] for c in pool if c["streamer_login"] == login]
        scope = "insgesamt" if cfg.get("selection_scope") == "global" else "je Kanal"
        self.store.log(f"Letzte {cfg['lookback_hours']} Stunden, {cfg.get('required_game_name') or 'alle Kategorien'}, Top {limit} {scope}: {len(pool)} passende Top-Clips, {added} neu.")
        return {"start": start.isoformat(), "end": end.isoformat(), "limit": limit,
                "scope": scope, "channels": summary, "added": added}

    def hold_ineligible(self, cfg=None):
        from .content_policy import facecam_reason, rejection_reason
        cfg = cfg or settings()
        for job in self.store.rows():
            if job["status"] not in {"queued", "ready", "failed"}:
                continue
            reason = rejection_reason(job["clip"], cfg)
            if not reason and job["status"] == "ready":
                reason = facecam_reason((job["result"] or {}).get("render"), cfg)
            if reason and self.store.transition(job["id"], job["status"], "policy_blocked"):
                self.store.update(job["id"], "policy_blocked", error=reason)

    def process_one(self, job):
        from .content_policy import rejection_reason
        reason = rejection_reason(job["clip"], settings())
        if reason:
            if self.store.transition(job["id"], "queued", "policy_blocked"):
                self.store.update(job["id"], "policy_blocked", error=reason)
            return
        if not self.store.transition(job["id"], "queued", "downloading"):
            return
        clip = job["clip"]
        directory = RUNTIME / "clips" / clip["id"]
        directory.mkdir(parents=True, exist_ok=True)
        self.stage = f"Verarbeite {clip['broadcaster_name']}: {clip.get('title', '')}"
        self.store.update(job["id"], "downloading", error="", attempts=job["attempts"] + 1)
        try:
            source = media.download(clip, directory)
            self.store.update(job["id"], "editing")
            result = media.process(source, directory, clip, settings(), self.store.log)
            from .content_policy import facecam_reason
            reason = facecam_reason(result.get("render"), settings())
            if reason:
                self.store.update(job["id"], "policy_blocked", result=result, error=reason)
                self.store.log(f"{clip['broadcaster_name']}: {reason}")
                return
            self.store.update(job["id"], "ready", result=result)
            self.store.log(f"Short fertig: {result['metadata']['title']}")
        except Exception as exc:
            self.store.update(job["id"], "failed", error=str(exc)[:3000])
            self.store.log(f"Clip {clip['id']} fehlgeschlagen: {str(exc)[:400]}")

    def _process_loop(self):
        while not self.shutdown.is_set():
            if not self.active.wait(1):
                self.stage = "Pausiert"
                continue
            cfg = settings()
            if self.scan_requested.is_set() or time.time() - self.last_scan >= cfg["poll_minutes"] * 60:
                self.scan_requested.clear()
                self.stage = "Suche aktuelle Top-Clips"
                try:
                    self.discover()
                except Exception as exc:
                    self.store.log(f"Clip-Suche fehlgeschlagen: {str(exc)[:400]}")
                self.last_scan = time.time()
            if not self.active.is_set():
                continue
            jobs = self.store.rows("queued")
            if jobs:
                self.process_one(jobs[0])
            else:
                self.stage = "Warte auf neue Clips"
                self.shutdown.wait(2)

    def publish_one(self):
        cfg = settings()
        if not self.active.is_set() or not cfg["publish_enabled"] or not cfg["channel_id"]:
            return
        self.hold_ineligible(cfg)
        job = self.store.ready_to_publish(time.time(), cfg["publish_interval_minutes"], cfg)
        if not job:
            return
        # Authenticate and verify destination before reserving an upload.
        with self.auth_lock:
            service = publisher.service_for_channel(cfg["channel_id"])
        if not self.active.is_set():
            return
        from .content_policy import facecam_reason, rejection_reason
        reason = (rejection_reason(job["clip"], settings())
                  or facecam_reason((job["result"] or {}).get("render"), settings()))
        if reason:
            if self.store.transition(job["id"], "ready", "policy_blocked"):
                self.store.update(job["id"], "policy_blocked", error=reason)
            return
        if not self.store.transition(job["id"], "ready", "uploading"):
            return
        self.publish_stage = f"Veröffentliche: {job['result']['metadata']['title']}"
        try:
            uploaded = publisher.upload(service, job["result"])
            video_id = uploaded["id"]
            status = "published" if uploaded["privacy"] == "public" else "uploaded_private"
            published = time.time()
            # A receipt survives a process crash between the network response and DB commit.
            from .state import atomic_json
            atomic_json(RUNTIME / "clips" / job["id"] / "youtube_receipt.json",
                        {"video_id": video_id, "published": published, "channel_id": cfg["channel_id"], "status": status})
            self.store.update(job["id"], status, youtube_id=video_id, published=published, error="")
            if status == "published":
                self.store.log(f"Auf {cfg['channel_title']} veröffentlicht: https://youtu.be/{video_id}")
            else:
                self.store.log(f"YouTube meldet Sichtbarkeit {uploaded['privacy']}: https://youtu.be/{video_id} – bitte in Studio prüfen.")
        except publisher.UploadProjectQuotaReached as exc:
            self.store.defer_uploads(time.time() + 24 * 60 * 60)
            self.store.update(job["id"], "ready", error=str(exc))
            self.store.log("Google-API-Uploadkontingent ausgeschöpft. Neuer Versuch frühestens in 24 Stunden; das Clip-Alter wird davor erneut geprüft.")
        except publisher.UploadLimitReached as exc:
            # An explicit rejection is safe to retry after YouTube's waiting period.
            retry_at = time.time() + 24 * 60 * 60
            self.store.defer_uploads(retry_at)
            self.store.update(job["id"], "ready", error=str(exc))
            self.store.log("YouTube-Tageslimit erreicht. Fertige Clips bleiben gespeichert; Uploads werden in 24 Stunden erneut versucht.")
        except Exception as exc:
            self.store.update(job["id"], "upload_unknown", error=str(exc)[:3000])
            self.store.log("Upload-Ergebnis unklar. Veröffentlichung angehalten; bitte YouTube Studio prüfen.")
        finally:
            self.publish_stage = ""

    def _publish_loop(self):
        while not self.shutdown.is_set():
            try:
                self.publish_one()
            except Exception as exc:
                self.store.log(f"YouTube noch nicht bereit: {str(exc)[:300]}")
                self.shutdown.wait(55)
            self.shutdown.wait(5)

    def retry(self, clip_id):
        job = self.store.get(clip_id)
        if not job or job["status"] != "failed":
            raise ValueError("Nur fehlgeschlagene Schnittjobs können automatisch wiederholt werden.")
        self.store.update(clip_id, "queued", error="")

    def skip(self, clip_id):
        job = self.store.get(clip_id)
        if not job or job["status"] not in {"queued", "failed", "ready"}:
            raise ValueError("Ein laufender oder veröffentlichter Clip kann nicht übersprungen werden.")
        if not self.store.transition(clip_id, job["status"], "skipped"):
            raise ValueError("Der Clip wird inzwischen verarbeitet. Bitte den aktuellen Status prüfen.")

    def reconcile(self, clip_id, video_id):
        import re
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise ValueError("Bitte die 11-stellige YouTube-Video-ID angeben.")
        job = self.store.get(clip_id)
        if not job or job["status"] != "upload_unknown":
            raise ValueError("Dieser Clip hat keinen unklaren Upload.")
        self.store.update(clip_id, "published", youtube_id=video_id, published=time.time(), error="")
        self.store.log(f"Vorhandenen Upload für {clip_id} übernommen. Weitere Uploads folgen dem eingestellten Abstand.")

    def snapshot(self):
        cfg = settings()
        from .scheduling import batch_snapshot
        from .learning import dashboard_learning
        reports = [{k: v for k, v in report.items() if k != "snapshot"} for report in self.store.report_rows()]
        return {"settings": cfg, "active": self.active.is_set(), "stage": self.stage,
                "reports": reports,
                "learning": dashboard_learning(self.store),
                "publish_stage": self.publish_stage, "last_scan": self.last_scan,
                "upload_blocked_until": self.store.upload_blocked_until(),
                "next_publish": self.store.next_publish(time.time(), cfg["publish_interval_minutes"], cfg),
                "publish_batch": batch_snapshot(self.store, cfg),
                "twitch_connected": bool(secrets().get("client_id") and secrets().get("client_secret")),
                "youtube_client": publisher.CLIENT.exists(), "youtube_connected": publisher.TOKEN.exists() and bool(cfg["channel_id"]),
                "jobs": self.store.rows(), "events": self.store.event_rows()}
