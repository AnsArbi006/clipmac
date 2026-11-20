"""CM-012 B/C: score gate and truthful, non-duplicating platform states with simulated uploaders."""

import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from clipmac_windows import scoring
from clipmac_windows.engine import Adapters, Engine
from clipmac_windows.queue import Queue
from clipmac_windows.uploaders import FakeUploader, Pause, TikTokUploader

CHAT = {"messages": 45, "baseline_messages": 5, "participants": 25, "baseline_participants": 5}
GOOD = {k: {"value": 2} for k in ("hook", "context", "payoff")}


class ScoreTests(unittest.TestCase):
    def test_chat_scaling(self):
        self.assertEqual(scoring.chat_component(5, 5), 0)
        self.assertEqual(scoring.chat_component(25, 5), 100)
        self.assertEqual(scoring.chat_component(15, 5), 50)
        self.assertEqual(scoring.chat_component(100, 0), 100)  # denominator at least 1

    def decide(self, **kw):
        args = dict(chat=CHAT, evidence=GOOD, category_ok=True, coverage_ok=True, technical_errors=[], duration=40)
        args.update(kw)
        return scoring.decide(**args)

    def test_good_clip_eligible(self):
        d = self.decide()
        self.assertTrue(d["eligible"])
        self.assertEqual(d["version"], scoring.VERSION)

    def test_missing_chat_or_llm_never_releases(self):
        self.assertFalse(self.decide(chat=None)["eligible"])
        self.assertIsNone(self.decide(evidence={})["score"])
        self.assertFalse(self.decide(evidence={})["eligible"])

    def test_context_and_payoff_minimum(self):
        evidence = {**GOOD, "context": {"value": 0}}
        d = self.decide(evidence=evidence)
        self.assertFalse(d["eligible"])

    def test_threshold_category_coverage_technical(self):
        self.assertFalse(self.decide(threshold=100, chat={**CHAT, "messages": 10})["eligible"])
        self.assertFalse(self.decide(category_ok=False)["eligible"])
        self.assertFalse(self.decide(coverage_ok=False)["eligible"])
        self.assertFalse(self.decide(technical_errors=["A/V"])["eligible"])
        self.assertFalse(self.decide(duration=130)["eligible"])
        with self.assertRaises(ValueError):
            self.decide(threshold=101)


def make_engine(root, scenarios, **cfg):
    uploaders = {p: FakeUploader(p, scenarios.get(p, ["public"])) for p in ("tiktok", "youtube")}
    adapters = Adapters(lookup=None, capture=None, chat=None, transcribe=None, ask=None, uploaders=uploaders)
    base = {"streamers": ["a", "b", "c", "d"], "score_threshold": 70, "upload_enabled": True,
            "accounts": {"tiktok": "demo-konto", "youtube": "demo-konto"}, **cfg}
    engine = Engine(root, base, adapters, demo=True)
    engine.running.set()
    return engine, uploaders


def add_clip(queue, key, eligible=True, score=90):
    queue.begin_clip({"id": key, "channel": "a"})
    queue.finish_clip(key, {"eligible": eligible, "score": score, "metadata": {"title": "t", "description": "", "tags": []}})


def step(engine):
    enabled = {p for p in engine.cfg.get("platforms_enabled", ("tiktok", "youtube"))
               if engine.platform_pause[p][0] <= time.time() and engine._package_ok(p) and engine._account_ok(p)}
    item = engine.queue.claim(engine.cfg["streamers"], enabled, engine.cfg["score_threshold"])
    if item:
        engine._publish(item)
    return item


def posts(engine, key):
    return {p: v["status"] for p, v in engine.queue.clip(key) and engine.queue.snapshot()[0]["posts"].items()}


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def status(self, engine, key):
        return {p: v["status"] for p, v in next(c for c in engine.queue.snapshot() if c["id"] == key)["posts"].items()}

    def test_tiktok_first_then_youtube_and_no_repeat(self):
        engine, up = make_engine(self.root, {})
        add_clip(engine.queue, "c" * 32)
        self.assertEqual(step(engine)["platform"], "tiktok")
        self.assertEqual(step(engine)["platform"], "youtube")
        self.assertIsNone(step(engine))
        self.assertEqual(self.status(engine, "c" * 32), {"tiktok": "public", "youtube": "public"})
        self.assertEqual(len(up["tiktok"].calls) + len(up["youtube"].calls), 2)

    def test_packages_of_three_then_one_hour_pause(self):
        engine, up = make_engine(self.root, {})
        for i in range(5):
            add_clip(engine.queue, str(i) * 32)
        for _ in range(6):                                    # 3 clips x TikTok+YouTube
            self.assertIsNotNone(step(engine))
        self.assertIsNone(step(engine))                       # 4th waits: package full
        self.assertGreater(engine.platform_pause["youtube"][0], time.time() + 3500)
        q = engine.queue
        self.assertEqual(q.package_wait("youtube", 3, 3600, now=time.time() + 3601), 0)
        with q.db() as db:                                    # simulate the hour passing
            db.execute("UPDATE posts SET sent_at = sent_at - 3700")
        engine.platform_pause = {p: (0, "") for p in ("tiktok", "youtube")}
        self.assertIsNotNone(step(engine))                    # next package starts
        self.assertEqual(len(up["tiktok"].calls), 4)

    def test_not_eligible_never_posted(self):
        engine, up = make_engine(self.root, {})
        add_clip(engine.queue, "d" * 32, eligible=False, score=95)
        self.assertIsNone(step(engine))
        self.assertEqual(up["tiktok"].calls, [])

    def test_tiktok_fails_youtube_still_posts_and_retry_only_tiktok(self):
        engine, up = make_engine(self.root, {"tiktok": ["failed", "public"], "youtube": ["public"]})
        key = "e" * 32
        add_clip(engine.queue, key)
        step(engine); step(engine)
        self.assertEqual(self.status(engine, key), {"tiktok": "failed", "youtube": "public"})
        self.assertTrue(engine.retry(key, "tiktok"))
        self.assertFalse(engine.retry(key, "youtube"))
        step(engine)
        self.assertEqual(self.status(engine, key), {"tiktok": "public", "youtube": "public"})
        self.assertEqual(len(up["youtube"].calls), 1)

    def test_youtube_fails_tiktok_success_kept(self):
        engine, up = make_engine(self.root, {"youtube": ["failed"]})
        key = "f" * 32
        add_clip(engine.queue, key)
        step(engine); step(engine)
        self.assertEqual(self.status(engine, key), {"tiktok": "public", "youtube": "failed"})
        engine.retry(key, "youtube"); step(engine)
        self.assertEqual(len(up["tiktok"].calls), 1)

    def test_moderation_review_then_public(self):
        engine, up = make_engine(self.root, {"tiktok": ["review"]})
        key = "a1" * 16
        add_clip(engine.queue, key)
        step(engine)
        self.assertEqual(self.status(engine, key)["tiktok"], "review")
        self.assertIsNone(engine.queue.snapshot()[0]["posts"]["tiktok"]["url"])  # no green tick, no link yet
        with engine.queue.db() as db:
            db.execute("UPDATE posts SET updated=0")
        engine._check_reviews()
        self.assertEqual(self.status(engine, key)["tiktok"], "review")
        with engine.queue.db() as db:
            db.execute("UPDATE posts SET updated=0")
        engine._check_reviews()
        self.assertEqual(self.status(engine, key)["tiktok"], "public")

    def test_unknown_is_never_retried(self):
        engine, up = make_engine(self.root, {"tiktok": ["unknown"]})
        key = "b2" * 16
        add_clip(engine.queue, key)
        step(engine); step(engine); step(engine)
        self.assertEqual(self.status(engine, key)["tiktok"], "unknown")
        self.assertFalse(engine.retry(key, "tiktok"))
        self.assertEqual(len(up["tiktok"].calls), 1)

    def test_quota_pauses_without_sending_and_unblocks_youtube(self):
        engine, up = make_engine(self.root, {"tiktok": ["quota", "public"]})
        key = "c3" * 16
        add_clip(engine.queue, key)
        step(engine)
        self.assertEqual(self.status(engine, key)["tiktok"], "waiting")
        self.assertGreater(engine.platform_pause["tiktok"][0], time.time())
        self.assertEqual(step(engine)["platform"], "youtube")  # TikTok pause does not block YouTube
        engine.platform_pause["tiktok"] = (0, "")
        step(engine)
        self.assertEqual(self.status(engine, key), {"tiktok": "public", "youtube": "public"})

    def test_login_required_pauses_platform(self):
        engine, _ = make_engine(self.root, {"youtube": ["login", "public"]}, platforms_enabled=["youtube"])
        add_clip(engine.queue, "d4" * 16)
        step(engine)
        self.assertIn("Anmeldung", engine.platform_pause["youtube"][1])

    def test_crash_after_send_becomes_unknown_on_restart(self):
        engine, _ = make_engine(self.root, {})
        key = "e5" * 16
        add_clip(engine.queue, key)
        item = engine.queue.claim(["a"], {"tiktok"}, 70)
        engine.queue.submitted(item)      # process dies here
        restarted = Queue(self.root / "clipmac-windows.sqlite")
        status = {p: v["status"] for p, v in restarted.snapshot()[0]["posts"].items()}
        self.assertEqual(status["tiktok"], "unknown")

    def test_crash_before_send_retries_on_restart(self):
        engine, _ = make_engine(self.root, {})
        add_clip(engine.queue, "f6" * 16)
        engine.queue.claim(["a"], {"tiktok"}, 70)
        restarted = Queue(self.root / "clipmac-windows.sqlite")
        self.assertEqual(restarted.snapshot()[0]["posts"]["tiktok"]["status"], "waiting")

    def test_stop_prevents_new_posts(self):
        engine, up = make_engine(self.root, {})
        add_clip(engine.queue, "a7" * 16)
        engine.stop()
        self.assertFalse(engine.running.is_set())
        # The publisher loop only claims while running; emulate one loop pass.
        if engine.running.is_set():
            step(engine)
        self.assertEqual(up["tiktok"].calls, [])

    def test_unconfirmed_account_blocks(self):
        engine, up = make_engine(self.root, {}, accounts={})
        add_clip(engine.queue, "b8" * 16)
        self.assertIsNone(step(engine))
        self.assertIn("bestätigen", engine.platform_pause["tiktok"][1])
        engine.confirm_account("tiktok")
        self.assertEqual(step(engine)["platform"], "tiktok")

    def test_double_submit_rejected(self):
        engine, _ = make_engine(self.root, {})
        add_clip(engine.queue, "c9" * 16)
        item = engine.queue.claim(["a"], {"tiktok"}, 70)
        engine.queue.submitted(item)
        with self.assertRaises(RuntimeError):
            engine.queue.submitted(item)


class RealAdapterGuards(unittest.TestCase):
    def test_live_adapters_locked_in_tests(self):
        with self.assertRaises(PermissionError):
            TikTokUploader(".")

    def test_tiktok_review_until_public_and_private_never_green(self):
        calls = []

        def request(method, path, token, body=None):
            calls.append(path)
            if path.endswith("creator_info/query/"):
                return 200, {"data": {"privacy_level_options": ["SELF_ONLY"]}}
            if path.endswith("video/init/"):
                return 200, {"data": {"publish_id": "p1", "upload_url": "https://upload.example/x"},
                             "error": {"code": "ok"}}
            return 200, {"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [1]}}

        with tempfile.TemporaryDirectory() as tmp:
            creds = Path(tmp) / "credentials"
            creds.mkdir()
            (creds / "tiktok_token.json").write_text('{"access_token": "t", "expires_at": %d}' % (time.time() + 999))
            video = Path(tmp) / "v.mp4"
            video.write_bytes(b"0" * 100)
            up = TikTokUploader(tmp, live_allowed=True, request=request, put=lambda url, path: 201)
            sent = []
            outcome = up.upload(video, {"title": "t", "tags": ["gta6"]}, lambda: sent.append(1))
            self.assertEqual((outcome["status"], sent), ("review", [1]))
            # Private-only (unaudited app): completed but not public -> stays "review".
            self.assertEqual(up.check(outcome["receipt"])["status"], "review")

    def test_tiktok_rate_limit_pauses_before_send(self):
        def request(method, path, token, body=None):
            if path.endswith("creator_info/query/"):
                return 200, {"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE"]}}
            return 429, {"error": {"code": "rate_limit_exceeded"}}

        with tempfile.TemporaryDirectory() as tmp:
            creds = Path(tmp) / "credentials"
            creds.mkdir()
            (creds / "tiktok_token.json").write_text('{"access_token": "t", "expires_at": %d}' % (time.time() + 999))
            video = Path(tmp) / "v.mp4"
            video.write_bytes(b"0")
            up = TikTokUploader(tmp, live_allowed=True, request=request, put=lambda *a: 201)
            sent = []
            with self.assertRaises(Pause):
                up.upload(video, {"title": "t", "tags": []}, lambda: sent.append(1))
            self.assertEqual(sent, [])


class ServerTests(unittest.TestCase):
    def setUp(self):
        from clipmac_windows.engine import Adapters, Engine
        from clipmac_windows.server import serve
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        cfg = {"streamers": ["a", "b", "c", "d"], "score_threshold": 70}
        self.engine = Engine(root, cfg, Adapters(lookup=None, capture=None, chat=None, transcribe=None, ask=None,
                                                 uploaders={}))
        clip = root / "clips" / ("a" * 32)
        clip.mkdir(parents=True)
        (clip / "final.mp4").write_bytes(bytes(range(256)) * 4)
        self.server = serve(self.engine, 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response, data

    def test_state_and_index(self):
        response, data = self.request("GET", "/api/state")
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(data)["selected"], ["a", "b"])
        self.assertEqual(self.request("GET", "/")[0].status, 200)

    def test_video_range_for_playback(self):
        response, data = self.request("GET", f"/media/{'a' * 32}/final", headers={"Range": "bytes=10-19"})
        self.assertEqual(response.status, 206)
        self.assertEqual(data, bytes(range(10, 20)))

    def test_post_requires_same_origin_header(self):
        response, _ = self.request("POST", "/api/settings", body="{}", headers={"Content-Type": "text/plain"})
        self.assertEqual(response.status, 403)
        ok = {"Content-Type": "application/json", "X-ClipMac": "1"}
        response, _ = self.request("POST", "/api/settings", body=json.dumps({"score_threshold": 80}), headers=ok)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.engine.cfg["score_threshold"], 80)
        response, _ = self.request("POST", "/api/select", body=json.dumps({"channels": ["x"]}), headers=ok)
        self.assertEqual(response.status, 400)

    def test_foreign_host_rejected(self):
        response, _ = self.request("GET", "/api/state", headers={"Host": "evil.example"})
        self.assertEqual(response.status, 403)


if __name__ == "__main__":
    unittest.main()
