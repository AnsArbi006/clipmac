"""Isolated, single-video TikTok pilot. No automatic backlog publishing."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

from .state import ROOT, RUNTIME, atomic_json
from .environment import require_live

PROFILE = RUNTIME / "credentials" / "tiktok-browser"
RECEIPTS = RUNTIME / "tiktok"


class StopRequested(RuntimeError):
    pass


def account_name(value):
    value = value.removeprefix("@").lower().strip()
    if not re.fullmatch(r"[a-z0-9_.]{2,24}", value):
        raise ValueError("Ungültiger TikTok-Name")
    return value


def own_account(page):
    """Only a navigation link to the signed-in user's profile counts."""
    for selector in ('[data-e2e="nav-profile"]', 'a[aria-label="Profile"]',
                     'a[aria-label="Profil"]'):
        for node in page.locator(selector).all():
            href = node.get_attribute("href")
            if not href:
                parent = node.locator("xpath=ancestor::a[1]")
                href = parent.get_attribute("href") if parent.count() else None
            match = re.search(r"/@([a-zA-Z0-9_.]+)(?:[/?#]|$)", href or "")
            if match:
                return account_name(match[1])
    return None


@contextlib.contextmanager
def browser():
    require_live("TikTok-Browser")
    from playwright.sync_api import sync_playwright
    PROFILE.mkdir(parents=True, exist_ok=True, mode=0o700)
    PROFILE.chmod(0o700)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE), channel="chrome", headless=False,
            locale="en-US", viewport={"width": 1280, "height": 850})
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(15000)
            yield context, page
        finally:
            context.close()


def connect(account, timeout=600, should_stop=lambda: False):
    with browser() as (_, page):
        page.goto("https://www.tiktok.com/", wait_until="domcontentloaded")
        print(f"Bitte im neuen ClipMac-Browser bei @{account} anmelden. Warte auf Profil-Link.", flush=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if should_stop():
                raise StopRequested("Anmeldung gestoppt.")
            found = own_account(page)
            challenge = page.get_by_text(re.compile(r"Drag the slider|Verify to continue|Sicherheitsüberprüfung", re.I))
            if challenge.count() and challenge.first.is_visible():
                found = None
            if found:
                if found != account:
                    raise ValueError(f"Angemeldet ist @{found}, erwartet wird @{account}.")
                atomic_json(RECEIPTS / "account.json", {"account": found, "checked_at": time.time()})
                print(f"TikTok-Anmeldung für @{found} bestätigt.", flush=True)
                return
            page.wait_for_timeout(1000)
        raise RuntimeError("Anmeldung noch nicht bestätigt. Kein Upload gestartet.")


def clip_payload(clip_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", clip_id):
        raise ValueError("Ungültige Clip-ID")
    with sqlite3.connect(f"file:{RUNTIME / 'queue.sqlite'}?mode=ro", uri=True) as db:
        row = db.execute("SELECT result,status,clip FROM jobs WHERE id=?", (clip_id,)).fetchone()
        hold = db.execute("SELECT 1 FROM reports WHERE clip_id=? AND status='open'", (clip_id,)).fetchone()
        rating = db.execute("SELECT value FROM ratings WHERE clip_id=? ORDER BY id DESC LIMIT 1", (clip_id,)).fetchone()
    if not row or row[1] not in ("ready", "published") or hold or (rating and rating[0] == "bad"):
        raise ValueError("Clip nicht fertig, negativ bewertet oder durch Fehlermeldung gesperrt.")
    from .state import settings
    from .content_policy import rejection_reason
    reason = rejection_reason(json.loads(row[2]), settings())
    if reason:
        raise ValueError(reason)
    result = json.loads(row[0])
    file = Path(result["file"]).resolve()
    expected = (RUNTIME / "clips" / clip_id / "final.mp4").resolve()
    if file != expected or not file.is_file():
        raise ValueError("Fertige Clip-Datei fehlt oder liegt außerhalb des Clip-Ordners.")
    if getattr(file.stat(), "st_flags", 0) & 0x40000000:
        raise OSError("Videodatei ist ein iCloud-Platzhalter und muss lokal geladen werden.")
    # The user's captions should contain hashtags only, without source links.
    tags = list(dict.fromkeys(re.findall(r"#[\w]+", result["metadata"]["description"])))
    caption = " ".join(tags)
    if not caption or len(caption) > 150:
        raise ValueError("Hashtag-Beschreibung fehlt oder überschreitet das 150-Zeichen-Limit des Pilot-Uploaders.")
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    return {"clip_id": clip_id, "file": str(file), "caption": caption, "sha256": digest}


def receipt_path(account, clip_id):
    return RECEIPTS / account / f"{clip_id}.json"


def post_once(page, on_submit=None):
    """Never repeat a click when the server may have accepted the first one."""
    require_live("TikTok-Veröffentlichung")
    from tiktok_uploader import config
    dismiss_optional_dialog(page)
    if not page.get_by_text("Everyone", exact=True).first.is_visible():
        raise ValueError("Öffentliche Sichtbarkeit im Formular nicht bestätigt.")
    button = page.locator(f"xpath={config.selectors.upload.post}")
    button.wait_for(state="visible", timeout=180000)
    if on_submit:
        on_submit()
    button.click(timeout=180000)
    # Some accounts display a second, distinct confirmation dialog.
    confirm = page.locator(f"xpath={config.selectors.upload.post_now}")
    if confirm.is_visible():
        confirm.click()
    page.locator(f"xpath={config.selectors.upload.post_confirmation}").wait_for(
        state="attached", timeout=90000)


def dismiss_optional_dialog(page):
    title = page.get_by_text("Turn on automatic content checks?", exact=True)
    if title.is_visible():
        page.get_by_role("button", name="Cancel", exact=True).click()


def set_caption(page, description):
    dismiss_optional_dialog(page)
    # TikTok may initialize the caption from the filename asynchronously.
    # Wait for its upload placeholders, then use the editor's native keyboard path.
    page.wait_for_timeout(1500)
    for placeholder in page.get_by_text("Uploading...", exact=True).all():
        placeholder.wait_for(state="hidden", timeout=180000)
    field = page.locator('[contenteditable="true"]').first
    for attempt in range(3):
        field.click()
        field.press("Meta+A")
        field.press("Backspace")
        page.keyboard.insert_text(description + " ")
        field.press("Escape")
        field.press("Tab")
        page.wait_for_timeout(1000)
        if " ".join(field.inner_text().split()) == " ".join(description.split()):
            return
    raise ValueError("TikTok-Beschreibung stimmt nicht mit dem vorbereiteten Text überein.")


def publish(account, clip_id, session=None, should_stop=lambda: False):
    require_live("TikTok-Upload")
    payload = clip_payload(clip_id)
    receipt = receipt_path(account, clip_id)
    if receipt.exists():
        previous = json.loads(receipt.read_text())
        if previous.get("status") == "cancelled_before_post":
            receipt.rename(receipt.with_name(receipt.stem + f".attempt-{time.time_ns()}.json"))
        else:
            raise ValueError("Für diesen Clip existiert bereits ein TikTok-Versuch. Erst Ergebnis prüfen; kein automatischer Wiederholungsupload.")
    if should_stop():
        raise StopRequested("Upload gestoppt.")
    # Import only the form helper. Upstream AuthBackend prints cookies and is never called.
    from tiktok_uploader.upload import complete_upload_form
    logging.getLogger("tiktok_uploader").disabled = True
    logging.getLogger("tiktok_uploader.upload").disabled = True
    with (contextlib.nullcontext(session) if session else browser()) as (_, page):
        page.goto("https://www.tiktok.com/", wait_until="domcontentloaded")
        for _ in range(30):
            found = own_account(page)
            if found:
                break
            page.wait_for_timeout(1000)
        if found != account:
            raise ValueError("Zielkonto konnte nicht bestätigt werden. Bitte erneut verbinden.")
        if should_stop():
            raise StopRequested("Upload gestoppt.")
        record = {**payload, "account": account, "status": "posting", "stage": "preparing_form", "started": time.time(),
                  "upstream_commit": "1cea92dd4c815dbd5127ee4b3a0a7b6fabbaa5f0"}
        atomic_json(receipt, record)
        def submitted():
            if should_stop():
                raise StopRequested("Vor dem Veröffentlichen gestoppt.")
            current = clip_payload(clip_id)
            if current["sha256"] != payload["sha256"] or current["caption"] != payload["caption"]:
                raise ValueError("Clip wurde während der Vorbereitung geändert.")
            record.update(stage="submit_started", updated=time.time())
            atomic_json(receipt, record)
        try:
            # No upstream console output: it may include sensitive error payloads.
            with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink), \
                    patch("tiktok_uploader.upload._post_video", lambda page: post_once(page, submitted)), \
                    patch("tiktok_uploader.upload._set_description", set_caption), \
                    patch("tiktok_uploader.upload._set_interactivity", lambda *a, **kw: None), \
                    patch("tiktok_uploader.upload._clear", lambda locator: locator.fill("")):
                complete_upload_form(page, payload["file"], payload["caption"],
                                     schedule=None, skip_split_window=False,
                                     visibility="everyone", num_retries=1, headless=False)
            record.update(status="confirmation_received", updated=time.time())
        except BaseException as exc:
            if isinstance(exc, StopRequested) and record["stage"] == "preparing_form":
                record.update(status="cancelled_before_post", updated=time.time())
                atomic_json(receipt, record)
                raise
            record.update(status="upload_unknown", error_type=type(exc).__name__, updated=time.time())
            atomic_json(receipt, record)
            with contextlib.suppress(Exception):
                page.screenshot(path=str(receipt.with_suffix(".png")))
            raise RuntimeError("TikTok-Ergebnis unklar. Profil prüfen; nicht erneut hochladen.") from None
        atomic_json(receipt, record)
        print("TikTok bestätigt den Upload. Öffentliche Sichtbarkeit wird separat geprüft.", flush=True)
        page.screenshot(path=str(receipt.with_suffix(".png")))


def verify(account, clip_id, url):
    if not re.fullmatch(rf"https://www\.tiktok\.com/@{re.escape(account)}/video/[0-9]+", url):
        raise ValueError("Videolink passt nicht zum Zielkonto.")
    path = receipt_path(account, clip_id)
    record = json.loads(path.read_text())
    record.update(status="verified", video_url=url, verified_at=time.time(),
                  verification="operator_checked_video_on_profile")
    atomic_json(path, record)


def inspect_profile(account):
    """Read visible profile links; no posting or private API calls."""
    with browser() as (_, page):
        page.goto(f"https://www.tiktok.com/@{account}", wait_until="domcontentloaded")
        print("Profilprüfung geöffnet. Falls TikTok ein Puzzle zeigt, bitte im Browser selbst lösen.", flush=True)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            if page.locator(f'a[href*="/@{account}/video/"]').count():
                break
            page.wait_for_timeout(1000)
        screenshot = RECEIPTS / f"{account}-profile.png"
        page.screenshot(path=str(screenshot), full_page=True)
        items = []
        for node in page.locator('a[href*="/video/"]').all():
            href = node.get_attribute("href") or ""
            if f"/@{account}/video/" in href:
                items.append({"url": href, "label": node.inner_text()[:400],
                              "title": node.get_attribute("title") or ""})
        print(json.dumps({"account": account, "videos": items, "screenshot": str(screenshot)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("connect", "preview", "publish", "verify", "inspect"))
    parser.add_argument("--account", required=True)
    parser.add_argument("--clip")
    parser.add_argument("--url")
    args = parser.parse_args()
    account = account_name(args.account)
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    os.umask(0o077)
    with (RECEIPTS / "pilot.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "connect":
            connect(account)
        elif args.action == "inspect":
            inspect_profile(account)
        elif not args.clip:
            parser.error("--clip fehlt")
        elif args.action == "preview":
            print(json.dumps({"account": account, **clip_payload(args.clip)}, ensure_ascii=False, indent=2))
        elif args.action == "publish":
            publish(account, args.clip)
        elif not args.url:
            parser.error("--url fehlt")
        else:
            verify(account, args.clip, args.url)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never serialize browser state or vendor exception payloads.
        print(str(exc) if isinstance(exc, (ValueError, RuntimeError)) else f"TikTok-Pilot gestoppt: {type(exc).__name__}", flush=True)
        raise SystemExit(1)
