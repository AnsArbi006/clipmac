import json
from pathlib import Path

from .state import RUNTIME, atomic_json, settings
from .environment import require_live

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
CLIENT = RUNTIME / "credentials" / "youtube_client.json"
TOKEN = RUNTIME / "credentials" / "youtube_token.json"


class UploadLimitReached(RuntimeError):
    """YouTube explicitly rejected this upload before creating a video."""


class UploadProjectQuotaReached(RuntimeError):
    """Google explicitly rejected the daily video-upload project quota."""


def is_upload_project_quota_error(exc):
    try:
        error = json.loads(exc.content).get("error", {})
        return (exc.resp.status == 429
                and "Video Uploads per day" in error.get("message", "")
                and any(e.get("reason") == "rateLimitExceeded" for e in error.get("errors", [])))
    except (AttributeError, ValueError, TypeError):
        return False


def is_upload_limit_error(exc):
    try:
        payload = json.loads(exc.content)
        return exc.resp.status == 400 and any(
            item.get("reason") == "uploadLimitExceeded"
            for item in payload.get("error", {}).get("errors", []))
    except (AttributeError, ValueError, TypeError):
        return False


def save_client(payload):
    require_live("OAuth-Zugang speichern")
    installed = payload.get("installed", {})
    if not installed.get("client_id") or not installed.get("client_secret"):
        raise ValueError("Bitte die JSON-Datei einer Google OAuth-Desktop-App wählen.")
    # Only Google's official OAuth endpoints may receive the browser login.
    if installed.get("auth_uri") != "https://accounts.google.com/o/oauth2/auth" or installed.get("token_uri") != "https://oauth2.googleapis.com/token":
        raise ValueError("Unbekannte OAuth-Endpunkte in der Google-Datei.")
    atomic_json(CLIENT, payload, private=True)


def connect():
    require_live("YouTube-Anmeldung")
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    if not CLIENT.exists():
        raise RuntimeError("Zuerst Google OAuth-Desktop-JSON auswählen.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
    credentials = flow.run_local_server(host="localhost", port=0, timeout_seconds=180,
                                       authorization_prompt_message="Google-Anmeldung im Browser geöffnet.",
                                       success_message="YouTube verbunden. Du kannst dieses Fenster schließen.")
    service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    channels = service.channels().list(part="snippet", mine=True).execute().get("items", [])
    if len(channels) != 1:
        raise RuntimeError("Bitte bei Google genau den gewünschten YouTube-Kanal auswählen.")
    channel = channels[0]
    atomic_json(TOKEN, json.loads(credentials.to_json()), private=True)
    cfg = settings()
    cfg.update(channel_id=channel["id"], channel_title=channel["snippet"]["title"])
    atomic_json(RUNTIME / "settings.json", cfg)
    return cfg["channel_title"]


def service_for_channel(channel_id):
    require_live("YouTube-Zugriff")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    if not channel_id or not TOKEN.exists():
        raise RuntimeError("YouTube ist noch nicht verbunden.")
    credentials = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        atomic_json(TOKEN, json.loads(credentials.to_json()), private=True)
    if not credentials.valid:
        raise RuntimeError("Bitte YouTube erneut verbinden.")
    service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    channels = service.channels().list(part="id", mine=True).execute().get("items", [])
    if [c["id"] for c in channels] != [channel_id]:
        raise RuntimeError("Der angemeldete YouTube-Kanal stimmt nicht mit dem Zielkanal überein.")
    return service


def upload_body(metadata):
    return {
        "snippet": {"title": metadata["title"][:100], "description": metadata["description"][:4900],
                    "tags": metadata["tags"], "categoryId": "24", "defaultLanguage": "de"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }


def upload(service, result):
    require_live("YouTube-Upload")
    from googleapiclient.http import MediaFileUpload
    path = Path(result["file"])
    if not path.is_file():
        raise RuntimeError("Fertige Videodatei fehlt.")
    request = service.videos().insert(part="snippet,status", body=upload_body(result["metadata"]),
                                      media_body=MediaFileUpload(str(path), mimetype="video/mp4", chunksize=8*1024*1024, resumable=True),
                                      notifySubscribers=False)
    response = None
    while response is None:
        try:
            _, response = request.next_chunk(num_retries=2)
        except Exception as exc:
            if is_upload_project_quota_error(exc):
                raise UploadProjectQuotaReached("Google-API-Tageskontingent für Video-Uploads erreicht; Upload abgelehnt.") from exc
            if is_upload_limit_error(exc):
                raise UploadLimitReached("YouTube-Tageslimit erreicht; Upload wurde abgelehnt.") from exc
            raise
    if not response.get("id"):
        raise RuntimeError("YouTube hat keine Video-ID zurückgegeben.")
    return {"id": response["id"], "privacy": response.get("status", {}).get("privacyStatus", "unknown")}
