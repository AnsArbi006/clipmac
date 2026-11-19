# Vollständige Installation auf einem neuen Mac

Zielplattform: Apple Silicon, macOS, Python 3.10–3.12 (empfohlen 3.11), Git. Der schnelle Entwicklungsweg steht in der README und benötigt keine Konten/Modelle.

1. Repository einschließlich Submodul klonen. Die Git-Submodulreferenz fixiert die verwendete Twitch-Abfrage und Facecam-Erkennung. Die Upstream-run-all-Pipeline nicht starten.
2. Mit Homebrew FFmpeg Full (ASS/libass-Unterstützung) und Ollama installieren: `brew install ffmpeg-full ollama`. Google Chrome wird nur für reale TikTok-Nutzung benötigt.
3. Im Repository `python3.11 -m venv .venv` und `.venv/bin/python -m pip install -r requirements.lock.txt`. Die Lockdatei ist ein Snapshot der ursprünglichen macOS-Umgebung, kein plattformübergreifender Lock mit Paket-Hashes. Paketverfügbarkeit/Kompatibilität beim Installieren prüfen; nichts stillschweigend auf beliebige Versionen aktualisieren.
4. Whisper small einmalig herunterladen; danach erwartet die Pipeline ausschließlich lokale Dateien:

```sh
.venv/bin/python -c "from faster_whisper import download_model; download_model('small', output_dir=None, cache_dir='models/whisper')"
```

5. Das fixierte Submodul enthält die YuNet-Datei `models/face_detection_yunet_2023mar.onnx` (ca. 227 KB). `git submodule update --init` stellt diesen Stand her. Die Datei muss tatsächlich vorhanden sein; fehlende oder ungültige Gewichte vor dem ersten Rendern beheben. Die genaue Modell-Provenienz bleibt in den Drittanbieterhinweisen als offene Prüfung dokumentiert.
6. Ollama für das Projekt auf eigenem Port starten und das Modell herunterladen:

```sh
OLLAMA_HOST=127.0.0.1:11435 OLLAMA_MODELS="$PWD/models/ollama" OLLAMA_NO_CLOUD=1 ollama serve
```

In einem zweiten Terminal:

```sh
OLLAMA_HOST=127.0.0.1:11435 ollama pull qwen2.5:3b
```

Der Modellname ist ein Tag und noch kein unveränderlicher Digest. Modell-Provenienz ist ein Folgeauftrag in Aufgaben.md. Der bisherige Launcher erwartet Homebrew-Ollama unter `/opt/homebrew/bin/ollama`.

7. Arial Bold muss unter `/System/Library/Fonts/Supplemental/Arial Bold.ttf` verfügbar sein; Schrift wird nicht mitgeliefert. FFmpeg muss dieselbe Schrift zum Einbrennen finden.
8. Vor Konten zuerst synthetische Vorschau und Tests ausführen. Der umfassende lokale Render-Demotest `scripts/demo.py` benötigt zusätzlich die macOS-Stimme Anna und die oben geladenen Modelle; er erzeugt eigene Testbilder und Sprache, keine Uploads.
9. Erst bei gewünschtem Live-Betrieb `.venv/bin/python -m clipmac.launch` starten. Der Server bindet an `127.0.0.1:8768`, startet pausiert und erhält durch `caffeinate` den Wachzustand. Strg+C beendet den Server; der lokale Ollama-Dienst kann danach weiterlaufen.
10. Twitch-App-Zugang und Google-OAuth-Desktop-Client über die lokale Oberfläche einrichten. YouTube Data API v3 ist erforderlich. Kanalidentität wird vor Nutzung geprüft; bei einem Kanalwechsel zuerst pausieren. Anmeldungen, API-Freischaltungen und zusätzliche Rechte sind Aufgaben des Betreibers, nicht der CI.
11. Optional TikTok getrennt gemäß TIKTOK-PILOT.md installieren. Nach Kontoverbindung Einstellungen kontrollieren und erst dann bewusst die Automatik aktivieren.

## Betrieb und Wiederherstellung

Datenverzeichnis enthält SQLite-Warteschlange, Einstellungen, Credentials, Originale, Renderfassungen, Feedback und Uploadquittungen. Platzbedarf wächst; automatische Bereinigung ist noch nicht implementiert. Vor Updates bei geordnet beendeter App das gesamte Datenverzeichnis lokal sichern. Es enthält sensible Daten und gehört nicht auf GitHub.

Abgebrochene Bearbeitung kann wiederaufgenommen werden. Ein unklarer Uploadausgang muss anhand der Plattform und Quittungen geklärt werden. Nie die Datenbank löschen, um einen Upload erneut zu erzwingen: damit gehen Deduplizierung und Löschsperren verloren.

Eine frische Installation mit tatsächlichen API-Verbindungen ist keine CI-Abnahme. Dokumentierte Tests belegen nur ihren ausdrücklich beschriebenen Umfang.
