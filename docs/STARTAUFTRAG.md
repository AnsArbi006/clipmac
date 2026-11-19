# Startauftrag für einen zweiten Codex-/ChatGPT-Account

Diesen Text in einer Entwicklungsumgebung mit Zugriff auf das Repository verwenden:

> Arbeite ausschließlich am Repository https://github.com/AnsArbi006/clipmac.
> Lies AGENTS.md, README.md und Aufgaben.md. Implementiere zunächst CM-001 (optionale YouTube-Analytics-Anbindung), einschließlich synthetischer API-Antworten, Tests und Dokumentation. CM-000 ist bereits die Übergabebasis.
> Erstelle dafür den Branch task/CM-001-youtube-analytics und anschließend einen Pull Request. Andere Aufgaben bleiben unberührt. Nutze keine produktiven Zugangsdaten und führe keine echten Uploads oder Kontoverbindungen aus. Falls eine echte OAuth-Abnahme nötig ist, dokumentiere die Schritte für den Betreiber, statt Kontodaten anzufordern.
> Die Verarbeitung bleibt lokal. Analytics erweitert die Datensammlung; es gibt kein Modelltraining und keine automatische Änderung der Clip-Auswahl. Halte dich an die Abnahmekriterien und aktualisiere den Aufgabenstatus auf Zur Prüfung. Berichte, was getestet wurde und was noch nicht verifiziert ist.

## Umgebung

Ein öffentlicher Link erlaubt Lesen und Klonen, aber nicht automatisch Schreiben. Für einen PR muss die Umgebung mit einem berechtigten GitHub-Konto verbunden sein; alternativ einen Fork benutzen. Ein zweites ChatGPT-Abo verbindet weder Konten noch lokale Ordner automatisch.

```sh
git clone --recurse-submodules https://github.com/AnsArbi006/clipmac.git
cd clipmac
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m clipmac.dev
```

Die getestete Zielplattform ist macOS mit Python 3.10–3.12; CI verwendet Python 3.11. Die Untertiteltests benötigen Arial Bold aus macOS. Linux ist noch keine vollständige Render-Zielplattform.

## Übernahme in den Betrieb

PR und CI prüfen, dann nach Freigabe mergen. Deployment erfolgt separat: Warteschlange/Quittungen/Einstellungen sichern, laufende Jobs geordnet abschließen, kompatible Änderungen übernehmen und pausiert starten. Erst nach lokaler Prüfung aktiviert der Betreiber die Automatik. Das Entwickler-Repo wird niemals über das produktive runtime-Verzeichnis kopiert.
