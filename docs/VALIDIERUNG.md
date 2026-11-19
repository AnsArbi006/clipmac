# Validierung der Übergabebasis

Stand: 19.11.2026. Belege betreffen die bereinigte Entwicklungskopie, nicht den laufenden Produktionsbetrieb.

## Lokal geprüft

- Frische Python-3.10.5-Umgebung ohne Übernahme der produktiven site-packages angelegt; Entwicklungsdependencies aus öffentlichen Paketquellen und festgelegtem TikTok-Commit installiert. `requirements-dev.lock.txt` hält die verwendeten Versionen fest.
- Vollständige Unit-/Mock-/Entwicklungs-API-Suite: **110 Tests bestanden**, keine übersprungenen Tests. Enthält echte lokale HTTP-Aufrufe an eine synthetische Instanz und separate Prozesse für Upload-/Auth-Sperren.
- JavaScript-Dateien mit `node --check` geprüft.
- Synthetischen viersekündigen Clip mit FFmpeg (Farbmuster/Testton) erzeugt. In Chrome Vorschau geöffnet, laufende Wiedergabe und Entwicklungsbanner geprüft. Kein fremdes Video benutzt, kein Upload.
- Versehentlich übernommene Anmeldungen werden bei Eintritt in den Entwicklungsmodus abgewiesen; produktiver Standardordner und nichtleere unmarkierte Datenverzeichnisse werden nicht geöffnet.
- Importkonflikt behoben: das Twitch-Submodul enthält einen gleichnamigen TikTok-Helper. Installierte Pakete haben jetzt Vorrang; komplette Suite prüft beide Integrationen gemeinsam.
- Vor dem ersten Commit werden explizite Dateiliste und Veröffentlichungsscan geprüft. Keine Betriebshistorie, Zugangsdaten, Browserprofile oder Clip-Mediendateien im Root-Commit. Git-Submodul verweist auf den unveränderten öffentlichen Upstream-Commit.

- Ein frischer öffentlicher GitHub-Klon einschließlich Submodul bestand ebenfalls die damals vollständige Suite (109 Tests); der zusätzliche Launcher-Isolationstest wurde anschließend lokal ergänzt und bestanden.

## Getrennte Nachweise

GitHub Actions prüft einen frischen Checkout auf macOS 15/Python 3.11 ohne Produktionssecrets. Das Ergebnis ist unter dem Tests-Badge in der README sichtbar; maßgeblich ist der Lauf des jeweiligen Commit-SHA, nicht ein früher grüner Lauf.

## Nicht verifiziert / bewusst nicht ausgeführt

- Keine realen Twitch-Abfragen, YouTube-/TikTok-Uploads, Kontoverbindungen oder Änderungen der produktiven Konfiguration für diese Übergabe.
- Kein vollständiger Neuaufbau aller Render-Modelle und Live-Abhängigkeiten auf einem zweiten Mac; Produktions-Lockdatei ist ein historischer Snapshot.
- Keine Messung höherer Reichweite, keine neue Auswahl-KI, kein Modelltraining. CM-001 bis CM-010 bleiben Arbeitsaufträge.
- Keine Garantie gegen alle möglichen Secrets: Dateiauswahl, zusätzliche Musterprüfung und manuelle Durchsicht reduzieren das Risiko; der Scanner ist nicht vollständig.
- Modell- und Schriftlizenzen sind nicht von der MIT-Lizenz des eigenen Codes abgedeckt; siehe THIRD_PARTY_NOTICES.md.
