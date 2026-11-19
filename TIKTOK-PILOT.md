# TikTok-Anbindung

Die Anbindung ist ein lokaler Browser-Worker, keine garantierte offizielle Direct-Post-API. Browseränderungen, abgelaufene Anmeldung und CAPTCHAs können menschliche Eingriffe erfordern. Ein erfolgreiches früheres Posting beweist keinen störungsfreien Dauerbetrieb.

## Ablauf

- Start aktiviert im Paketmodus die automatische Übernahme vollständig abgeschlossener YouTube-Pakete. Aktuelle Kategorie-/Zeitfensterprüfung, Fehlerberichte und bereits vorhandene TikTok-Quittungen bleiben maßgeblich.
- Paketgröße/Pause stammen aus der Konfiguration. Das GTA-6-Beispiel nutzt höchstens fünf Clips und mindestens 60 Minuten Pause; fehlende passende Clips werden nicht durch beliebigen Rückstand ersetzt.
- Bei Paketgröße 1 existiert weiterhin der ältere einmalige Lauf über fertige freigegebene Clips. Dieser Modus ist nicht die empfohlene GTA-6-Konfiguration.
- Stoppen deaktiviert die Automatik. Ein bereits abgeschickter Upload wird noch zugeordnet. MacClip muss laufen und der Mac wach bleiben; Codex muss den Worker nicht überwachen.
- Status prüfen liest TikTok Studio, startet aber keine Uploads. Unklare Ergebnisse blockieren Wiederholungen.
- `pending_review` heißt: Upload zugeordnet, TikTok prüft. Erst `verified` bezeichnet bestätigte öffentliche Sichtbarkeit zum Prüfzeitpunkt.
- Geordnetes Beenden des Servers deaktiviert die Automatik. Nach einem Crash ist persistenter Zustand vorhanden; offene Ergebnisse zuerst prüfen, statt einen erneuten Post zu erzwingen.

## Getrennte Installation für Live-Betrieb

```sh
python3.11 -m venv .venv-tiktok
.venv-tiktok/bin/python -m pip install -r requirements.tiktok.lock.txt
.venv-tiktok/bin/python -m clipmac.tiktok connect --account DEIN_ACCOUNT
```

Google Chrome muss installiert sein. Das Browserprofil wird unter dem gewählten Datenverzeichnis in `credentials/tiktok-browser/` gespeichert und enthält eine Anmeldung. Nicht teilen oder committen. Der Nutzer meldet sich selbst an und erledigt CAPTCHAs; der Worker umgeht diese nicht.

Lokale Zustände: `tiktok/dashboard.json`, `automatic.json`, `stop.request`, Auftragsmanifeste und Quittungen unter `tiktok/<account>/`. Quittungen enthalten Datei-Hash und Posting-Ergebnis; Cookie-Werte werden nicht protokolliert. Im Entwicklungsmodus sind Browser, Post-Funktion und Worker-Start gesperrt; Tests verwenden Mocks.

## Implementierung

`tiktok_schedule.py` bestimmt geeignete YouTube-Pakete. `tiktok_service.py` verwaltet Automatik und Prozess, `tiktok_worker.py` führt Aufträge aus, `tiktok_batch.py` ordnet Studio-Beiträge zu. `tiktok.py` nutzt ausschließlich den Formularhelfer der festgelegten tiktok-uploader-Version, nicht deren Cookie-ausgebende Anmeldung.

Keine Posting- oder Sichtbarkeitsgarantie. Plattformbedingungen und Rechte müssen vor dem Live-Betrieb vom Betreiber geprüft werden.
