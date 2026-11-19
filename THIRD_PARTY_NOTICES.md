# Herkunft und Lizenzen

Die MIT-Lizenz im Projektroot gilt für den eigenen ClipMac-Code, nicht pauschal für Abhängigkeiten, Modelle, Schriften oder Videoinhalte. Keine Modellgewichte werden in den eigenen Root-Commit kopiert. Das referenzierte Twitch-Submodul enthält seinerseits ein YuNet-Modell; seine eigene Herkunft/Lizenz bleibt maßgeblich.

| Komponente | Verwendung / Herkunft | Bedingungen |
| --- | --- | --- |
| twitch-clipper | Git-Submodul https://github.com/coltonalmeida/twitch-clipper, Commit `eeb529df9dd0574187abb2d96e53858c4419ce28`; Twitch-API und Facecam-Helper | MIT, Copyright 2026 Colton Almeida; LICENSE im Submodul erhalten |
| tiktok-uploader | Python-Dependency https://github.com/wkaisertexas/tiktok-uploader, Commit `1cea92dd4c815dbd5127ee4b3a0a7b6fabbaa5f0`; Formularhelper | MIT, Copyright 2024 William Kaiser; Lizenz im Paket/Upstream |
| faster-whisper / CTranslate2 | lokale Spracherkennung, Paketversionen in Lockdatei | Jeweils MIT laut Upstream; eigene Lizenzdateien gelten |
| Whisper small | vortrainierte Sprachgewichte, separat bezogen | [OpenAI Whisper MIT](https://github.com/openai/whisper/blob/main/LICENSE); keine eigene Trainingsleistung |
| Ollama / Qwen2.5:3b | lokaler Titelgenerator; Ollama-Tag ohne festgehaltenen Modelldigest | Ollama-Code MIT; Modell separat. [Qwen2.5-3B-Instruct-Modellkarte](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct) nennt **qwen-research**, nicht pauschal Apache-2.0. Vor kommerzieller Nutzung konkrete Modelllizenz prüfen. |
| OpenCV / YuNet | Gesichtserkennung und Bildverarbeitung | OpenCV-Code und [YuNet-Modell](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) besitzen eigene Lizenzhinweise; die exakte Zuordnung der upstream eingebetteten ONNX-Datei zu einer Modellrevision ist hier noch nicht verifiziert |
| FFmpeg / libass / H.264-Encoder | Schnitt, Untertitelrendering und Export, Systeminstallation | FFmpeg-Bedingungen hängen von Build-Optionen und eingebundenen Bibliotheken ab; keine FFmpeg-Binaries in diesem Repo |
| Pillow | Schriftbreitenmessung | HPND-Lizenz; siehe installierte Distribution |
| Arial Bold | macOS-Systemschrift | Nicht mitgeliefert; keine Weiterverteilung durch dieses Repository |
| Playwright | TikTok-Browsersteuerung | Apache-2.0; Browser separat installiert |
| Google API/OAuth-Clients, yt-dlp, weitere Python-Pakete | Plattformanbindung/Download | Eigene Lizenzdateien der in den Lockdateien genannten Distributionen gelten |

Diese Übersicht ist keine vollständige Lizenzfreigabe für ein kommerzielles Produkt. Modelle werden weder in GitHub Actions geladen noch benötigt. Vor Distribution eines gebündelten Installers müssen alle konkret ausgelieferten Komponenten einschließlich Modellgewichten und Systembibliotheken geprüft werden.

MIT-Softwarelizenz und öffentliche Verfügbarkeit eines Twitch-Clips erlauben nicht automatisch dessen Wiederveröffentlichung. Der Betreiber benötigt die entsprechenden Rechte und muss Plattformbedingungen beachten. Dieses Repository enthält keine fremden Beispielclips, persönlichen Uploadhistorien oder Kontoanmeldungen.
