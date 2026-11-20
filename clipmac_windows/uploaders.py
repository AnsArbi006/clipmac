"""Separate TikTok/YouTube publishers. Each returns a truthful platform state.

States: waiting, uploading, review (submitted / in moderation), public (confirmed), failed,
unknown (sent, outcome unclear, never retried automatically), paused (limit/login/CAPTCHA, not sent).
"""

import json
import time
from http.client import HTTPSConnection, HTTPException
from pathlib import Path


class Pause(Exception):
    """Platform asks us to stop for now (quota, login, CAPTCHA, account mismatch). Nothing was sent."""

    def __init__(self, message, seconds=900):
        super().__init__(message)
        self.seconds = seconds


class Outcome(dict):
    def __init__(self, status, url=None, receipt=None, detail=""):
        super().__init__(status=status, url=url, receipt=receipt, detail=detail)


# ---------------------------------------------------------------- simulated (development) ----

class FakeUploader:
    """Deterministic scripted platform. Scenarios cycle per upload; never touches the network."""

    def __init__(self, platform, scenarios=None, account="demo-konto"):
        self.platform = platform
        self.scenarios = list(scenarios or ["public"])
        self.account_name = account
        self.calls = []
        self.checks = {}

    def account(self):
        return self.account_name

    def upload(self, path, meta, mark_sent):
        scenario = self.scenarios[len(self.calls) % len(self.scenarios)]
        self.calls.append((str(path), meta["title"], scenario))
        if scenario == "quota":
            raise Pause(f"{self.platform}: Tageslimit erreicht (simuliert).", 120)
        if scenario == "login":
            raise Pause(f"{self.platform}: Erneute Anmeldung nötig (simuliert).", 120)
        if scenario == "captcha":
            raise Pause(f"{self.platform}: Sicherheitsprüfung im Browser lösen (simuliert).", 120)
        mark_sent()
        n = len(self.calls)
        if scenario == "failed":
            return Outcome("failed", detail="Plattform hat den Upload abgelehnt (simuliert).")
        if scenario == "unknown":
            return Outcome("unknown", detail="Zeitüberschreitung nach Versand (simuliert). Bitte prüfen.")
        receipt = {"id": f"{self.platform}-{n}", "scenario": scenario}
        url = (f"https://www.tiktok.com/@{self.account_name}/video/{7000000000000000000 + n}"
               if self.platform == "tiktok" else f"https://youtu.be/demo{n:06d}")
        if scenario == "review":
            self.checks[receipt["id"]] = 2
            return Outcome("review", url=None, receipt={**receipt, "url": url}, detail="In Prüfung")
        return Outcome("public", url=url, receipt=receipt)

    def check(self, receipt):
        left = self.checks.get(receipt["id"], 0) - 1
        self.checks[receipt["id"]] = left
        if left > 0:
            return Outcome("review", receipt=receipt, detail="In Prüfung")
        return Outcome("public", url=receipt.get("url"), receipt=receipt)


# ------------------------------------------------------------------------------ YouTube ----

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
                  "https://www.googleapis.com/auth/youtube.readonly"]


class YouTubeUploader:
    """YouTube Data API v3 resumable upload with a local Windows OAuth token."""

    platform = "youtube"

    def __init__(self, root, *, live_allowed=False):
        if not live_allowed:
            raise PermissionError("YouTube-Upload ist im Testbetrieb gesperrt.")
        self.credentials_dir = Path(root) / "credentials"
        self._service = None

    def service(self):
        if self._service is None:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            token = self.credentials_dir / "youtube_token.json"
            if not token.is_file():
                raise Pause("YouTube nicht verbunden. Im Dashboard „YouTube verbinden“ ausführen.", 3600)
            creds = Credentials.from_authorized_user_file(str(token), YOUTUBE_SCOPES)
            if not creds.valid:
                if creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except Exception:
                        raise Pause("YouTube-Anmeldung abgelaufen. Bitte neu verbinden.", 3600) from None
                    token.write_text(creds.to_json(), encoding="utf-8")
                else:
                    raise Pause("YouTube-Anmeldung abgelaufen. Bitte neu verbinden.", 3600)
            self._service = build("youtube", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def account(self):
        items = self.service().channels().list(part="snippet", mine=True).execute().get("items", [])
        return items[0]["snippet"]["title"] if items else None

    def upload(self, path, meta, mark_sent):
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
        body = {"snippet": {"title": meta["title"], "description": meta["description"], "tags": meta["tags"],
                            "categoryId": "20"},
                "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
        request = self.service().videos().insert(part="snippet,status", body=body,
                                                 media_body=MediaFileUpload(str(path), chunksize=-1, resumable=True))
        mark_sent()
        try:
            response = None
            while response is None:
                _, response = request.next_chunk()
        except HttpError as exc:
            reason = str(exc)
            if "quotaExceeded" in reason or "uploadLimitExceeded" in reason:
                return Outcome("failed", detail="YouTube-Quota/Uploadlimit erreicht. Morgen erneut.")
            return Outcome("unknown", detail="YouTube-Antwort unklar. Im Studio prüfen.")
        except (OSError, HTTPException):
            return Outcome("unknown", detail="Verbindung während Upload getrennt. Im Studio prüfen.")
        video_id = response.get("id")
        receipt = {"id": video_id}
        return self.check(receipt) if video_id else Outcome("unknown", detail="Keine Video-ID erhalten.")

    def check(self, receipt):
        items = self.service().videos().list(part="status", id=receipt["id"]).execute().get("items", [])
        if not items:
            return Outcome("review", receipt=receipt, detail="Verarbeitung läuft")
        status = items[0]["status"]
        url = f"https://youtu.be/{receipt['id']}"
        if status.get("uploadStatus") in {"rejected", "failed"}:
            return Outcome("failed", url=url, receipt=receipt, detail=f"YouTube: {status.get('uploadStatus')}")
        if status.get("uploadStatus") == "processed" and status.get("privacyStatus") == "public":
            return Outcome("public", url=url, receipt=receipt)
        return Outcome("review", url=None, receipt={**receipt, "url": url}, detail="Verarbeitung läuft")


def connect_youtube(root, *, live_allowed=False):
    """Interactive local OAuth (browser on this PC). Client file stays in the Windows data folder."""
    if not live_allowed:
        raise PermissionError("Kontoanmeldung ist im Testbetrieb gesperrt.")
    from google_auth_oauthlib.flow import InstalledAppFlow
    folder = Path(root) / "credentials"
    client = folder / "youtube_client_secret.json"
    if not client.is_file():
        raise FileNotFoundError("youtube_client_secret.json fehlt im Ordner credentials.")
    creds = InstalledAppFlow.from_client_secrets_file(str(client), YOUTUBE_SCOPES).run_local_server(port=0)
    (folder / "youtube_token.json").write_text(creds.to_json(), encoding="utf-8")


# ------------------------------------------------------------------------------- TikTok ----

def _tiktok_json(method, path, token, body=None, host="open.tiktokapis.com"):
    connection = HTTPSConnection(host, timeout=30)
    try:
        connection.request(method, path, body=json.dumps(body) if body is not None else None,
                           headers={"Authorization": f"Bearer {token}",
                                    "Content-Type": "application/json; charset=UTF-8"})
        response = connection.getresponse()
        return response.status, json.loads(response.read(65536) or b"{}")
    finally:
        connection.close()


class TikTokUploader:
    """TikTok Content Posting API (Direct Post). Official API: no browser automation, no CAPTCHA bypass.

    Requires an app with the video.publish scope and a user access token stored locally.
    Unaudited apps may only post privately; the state then remains "review", never "public".
    """

    platform = "tiktok"

    def __init__(self, root, *, live_allowed=False, request=_tiktok_json, put=None):
        if not live_allowed:
            raise PermissionError("TikTok-Upload ist im Testbetrieb gesperrt.")
        self.root = Path(root)
        self.request = request
        self.put = put or self._put

    def token(self):
        path = self.root / "credentials" / "tiktok_token.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("expires_at", 0) < time.time() + 60:
                raise Pause("TikTok-Anmeldung abgelaufen. Bitte neu verbinden.", 3600)
            return data["access_token"]
        except (OSError, ValueError, KeyError):
            raise Pause("TikTok nicht verbunden. Zugang im Dashboard hinterlegen.", 3600) from None

    def account(self):
        status, data = self.request("GET", "/v2/user/info/?fields=display_name,username", self.token())
        if status != 200:
            raise Pause("TikTok-Konto nicht lesbar. Anmeldung prüfen.", 900)
        user = data.get("data", {}).get("user", {})
        return user.get("username") or user.get("display_name")

    def _put(self, url, path):
        from urllib.parse import urlsplit
        size = Path(path).stat().st_size
        parts = urlsplit(url)
        connection = HTTPSConnection(parts.netloc, timeout=300)
        try:
            with open(path, "rb") as file:
                connection.request("PUT", parts.path + ("?" + parts.query if parts.query else ""), body=file,
                                   headers={"Content-Type": "video/mp4", "Content-Length": str(size),
                                            "Content-Range": f"bytes 0-{size - 1}/{size}"})
                return connection.getresponse().status
        finally:
            connection.close()

    def upload(self, path, meta, mark_sent):
        token = self.token()
        status, info = self.request("POST", "/v2/post/publish/creator_info/query/", token, {})
        if status != 200:
            raise Pause("TikTok-Konto derzeit nicht bereit. Später erneut.", 900)
        options = info.get("data", {}).get("privacy_level_options") or []
        privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in options else (options[0] if options else "SELF_ONLY")
        size = Path(path).stat().st_size
        body = {"post_info": {"title": f"{meta['title']} {' '.join('#' + t for t in meta['tags'])}"[:2000],
                              "privacy_level": privacy, "disable_comment": False},
                "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size,
                                "total_chunk_count": 1}}
        status, init = self.request("POST", "/v2/post/publish/video/init/", token, body)
        error = init.get("error", {}).get("code", "")
        if status == 429 or error in {"rate_limit_exceeded", "spam_risk_too_many_posts"}:
            raise Pause("TikTok-Postinglimit erreicht. Pause.", 3600)
        if status != 200 or error not in {"", "ok"}:
            raise Pause(f"TikTok hat den Upload nicht angenommen ({error or status}).", 1800)
        publish_id = init["data"]["publish_id"]
        mark_sent()
        try:
            put_status = self.put(init["data"]["upload_url"], path)
        except (OSError, HTTPException):
            return Outcome("unknown", receipt={"publish_id": publish_id, "privacy": privacy},
                           detail="Verbindung beim Senden getrennt. In TikTok prüfen.")
        if put_status not in (200, 201):
            return Outcome("unknown", receipt={"publish_id": publish_id, "privacy": privacy},
                           detail="TikTok-Datei-Upload unklar. In TikTok prüfen.")
        return Outcome("review", receipt={"publish_id": publish_id, "privacy": privacy}, detail="In Prüfung")

    def check(self, receipt):
        status, data = self.request("POST", "/v2/post/publish/status/fetch/", self.token(),
                                    {"publish_id": receipt["publish_id"]})
        if status != 200:
            return Outcome("review", receipt=receipt, detail="In Prüfung")
        info = data.get("data", {})
        state = info.get("status")
        if state == "FAILED":
            return Outcome("failed", receipt=receipt, detail=f"TikTok: {info.get('fail_reason', 'abgelehnt')}")
        ids = info.get("publicaly_available_post_id") or info.get("publicly_available_post_id") or []
        if state == "PUBLISH_COMPLETE" and ids and receipt.get("privacy") == "PUBLIC_TO_EVERYONE":
            account = receipt.get("account") or ""
            url = f"https://www.tiktok.com/@{account}/video/{ids[0]}" if account else f"https://www.tiktok.com/video/{ids[0]}"
            return Outcome("public", url=url, receipt=receipt)
        return Outcome("review", receipt=receipt, detail="In Prüfung" if state != "PUBLISH_COMPLETE"
                       else "Veröffentlicht, aber nicht öffentlich sichtbar (App-Prüfung/Privatsphäre).")
