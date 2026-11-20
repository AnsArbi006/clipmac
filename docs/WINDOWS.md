# ClipMac Windows – Start und Einrichtung (CM-012)

Eigenständige Windows-App: überwacht bis zu zwei Twitch-Livestreams, erkennt Chat-Spitzen, schneidet
Highlights lokal und veröffentlicht geeignete Clips automatisch auf TikTok und danach YouTube.
Kein Mac, keine gemeinsame Warteschlange, kein Abgleich mit Mac-Uploads. GitHub dient nur dem Code.

## 1. Voraussetzungen (einmalig)

1. **Python 3.11 oder 3.12** von python.org (bei der Installation „Add python.exe to PATH“ anhaken).
2. **FFmpeg** (enthält ffprobe): `winget install Gyan.FFmpeg` – danach neues Terminal öffnen, `ffmpeg -version` prüfen.
3. **Streamlink**: `winget install Streamlink.Streamlink` (nur für den Livebetrieb).
4. **Ollama** (lokale KI): `winget install Ollama.Ollama`, dann `ollama pull qwen2.5:3b`.
5. Im Repository-Ordner:

```bat
py -3.12 -m venv .venv-windows
.venv-windows\Scripts\python -m pip install -r requirements-windows.txt
```

## 2. Demo ohne Konten (empfohlen zuerst)

```bat
.venv-windows\Scripts\python -m clipmac_windows --demo
```

oder Doppelklick auf `ClipMac Windows starten.cmd` und „Demo“ wählen. Das Dashboard öffnet sich unter
<http://127.0.0.1:8765/>. „Start“ drücken. Zwei synthetische Streams (FFmpeg-Testbild + Ton) und
geskriptete Chats laufen; nach etwa drei Minuten erscheinen fertig geschnittene Clips mit Vorschau.
Uploads sind **simuliert** (TikTok: In Prüfung → öffentlich, öffentlich, unklar, Limit; YouTube: öffentlich,
abgelehnt …). Es wird nichts im Netz veröffentlicht. Demo-Daten liegen in `%LOCALAPPDATA%\ClipMacWindowsDemo`.

## 3. Livebetrieb einrichten

Datenordner: `%LOCALAPPDATA%\ClipMacWindows` (getrennt von Demo; nie ins Repository legen).
Dort einen Ordner `credentials` anlegen. **Keine Dateien von Mac übertragen, nichts committen.**

| Datei in `credentials\` | Inhalt | Zweck |
| --- | --- | --- |
| `twitch.json` | `{"client_id": "…", "client_secret": "…"}` | Live-Status/Kategorie (Helix, App-Zugang). App unter dev.twitch.tv anlegen. |
| `twitch_chat.json` | `{"login": "dein_twitch_name", "access_token": "…"}` | Chat **nur lesen**, Scope `chat:read`. Es werden keine Nachrichten gesendet; gespeichert werden nur Zählwerte pro 10 s, kein Chattext. |
| `youtube_client_secret.json` | OAuth-Client „Desktop-App“ aus der Google Cloud Console (YouTube Data API v3 aktivieren) | Upload |
| `tiktok_token.json` | `{"access_token": "…", "expires_at": <Unix-Zeit>}` | TikTok Content Posting API, Scope `video.publish` |

YouTube einmalig verbinden (öffnet den Browser auf diesem PC):

```bat
.venv-windows\Scripts\python -m clipmac_windows --connect-youtube
```

Starten:

```bat
.venv-windows\Scripts\python -m clipmac_windows
```

Im Dashboard: zwei Streamer wählen, bei TikTok/YouTube das angezeigte Zielkonto **bestätigen**,
„Automatisch veröffentlichen“ anhaken, Start. Der PC muss wach bleiben (die App verhindert Standby, solange sie läuft).

Whisper-Modell: Ordner `models\whisper-small` im Datenordner mit einem CTranslate2-Modell
(z. B. `Systran/faster-whisper-small`) befüllen; ohne Modell wird kein Clip freigegeben.

## 4. Regeln (v1, konservative Startwerte, kein Training)

- Chat-Spitze: 10-s-Fenster gegen 180-s-Baseline; mind. 15 Nachrichten, 5 Teilnehmer, 3× Rate, 3 MAD; max. 4 Nachrichten je Nutzer/Fenster.
- Reaktionsversatz 6 s, Kontext ±30 s, Zusammenführung innerhalb 60 s, max. 120 s.
- 5-Minuten-Ringpuffer, 5-s-Segmente, 5 GB Limit; unter 5 GB freiem Speicher pausiert die Aufnahme.
- Viral Score (experimentell): Chat 20 %, Teilnehmer 15 %, Einstieg 20 %, Kontext 20 %, Höhepunkt 25 %.
- Veröffentlichung nur bei Chat-Spitze, Score ≥ Schwelle (Standard 70), Kontext und Abschluss ≥ 1/2, GTA-6-Kategorie, alle technischen Prüfungen bestanden.
- Status pro Plattform: Wartet, Lädt hoch, In Prüfung, ✓ Öffentlich (nur nach Bestätigung), Fehlgeschlagen, Prüfen (unklar – wird nie automatisch wiederholt), Pausiert (Limit/Anmeldung).

## 5. Bekannte Grenzen

- TikTok: Ohne geprüfte („audited“) TikTok-App erlaubt die offizielle API nur private Posts. Der Status bleibt dann „In Prüfung“ und wird nie als öffentlich angezeigt.
- Facecam: statisches Facecam-Rechteck pro Streamer über `facecam_crops` in `settings.json`; automatische Gesichtserkennung ist auf Windows noch nicht angebunden.
- Echte Twitch-, Konto- und Upload-Abnahme sowie der Zwei-Stream-Lastlauf mit echten Streams sind **nicht** durch die Tests belegt.
