# ClipMac – Arbeitsaufträge für die Weiterentwicklung

Stand: 19.11.2026. Diese Liste beschreibt **offene Arbeit**, nicht bereits vorhandene Funktionen. Schwerpunkt: Engagement verstehen und interessante Momente erkennen. Der zweite Account bearbeitet jeweils **eine Aufgabe pro Pull Request** in dieser Entwicklungskopie.

## Verbindliche Entscheidungen

- Nur lokale KI-Inferenz; keine kostenpflichtigen KI-APIs. Gegenwärtig keine eigene Trainingspipeline.
- Mac-Pfad: neue Rankings zunächst nur zum Vergleich. Ausnahme CM-012: eigenständiger Windows-Live-Pfad mit automatischer Veröffentlichung geeigneter Highlights, ausdrücklich beauftragt am 20.11.2026.
- Bestehender Mac-Pfad: vier Streamer im GTA-6-Profil, sieben Stunden Aktualität, Top fünf pro Streamer, Pakete bis fünf mit mindestens 60 Minuten Pause. Windows-CM-012 besitzt eigene Recorder, Daten und Uploadqueue; keine geräteübergreifende Koordination.
- Subjektives Feedback, technische Defekte, Modellvorschläge und Plattform-Performance getrennt speichern und anzeigen.
- Keine Behauptung „Shadowban“, „viral“ oder „besserer Schnitt“ allein aus niedrigen/hohen Views.
- Keine echten Uploads, Kontoverbindungen oder Löschungen zur Entwicklung. Synthetischer Modus und Mock-APIs; reale Abnahme durch den Betreiber separat.

## Status und Arbeitsablauf

Status: **Offen → In Arbeit → Zur Prüfung → Erledigt**. Eine Aufgabe gilt erst nach erfüllten Kriterien, Review und Merge als erledigt. Kleine Teil-PRs sind erlaubt, wenn sie einzeln testbar sind; Gesamtstatus erst nach allen Kriterien abschließen.

Branch `task/CM-XXX-kurzer-name`. Im PR Aufgaben-ID, Problem, Änderung, Tests, Grenzen, Datenmigration und Rückweg nennen. Neue Tabellen additiv/versioniert migrieren, vorherige Daten und Quittungen erhalten. Keine Migration an der produktiven Datenbank testen. Nach Merge `Aufgaben.md` mit PR-Link und Abnahmebelegen aktualisieren. Nicht automatisch deployen.

Aufwand ist relativ: S = klar begrenzte Änderung, M = mehrere Komponenten, L = größere UI-/Datenflussänderung. Keine Zeitgarantie.

| ID | Priorität | Aufgabe | Aufwand | Abhängigkeiten | Status |
| --- | --- | --- | --- | --- | --- |
| CM-000 | P0 | Öffentliche Übergabebasis und Isolation | M | – | Erledigt |
| CM-001 | P1 | Optionale YouTube Analytics | M | CM-000 | Offen |
| CM-002 | P1 | Vergleichbares Engagement-Dashboard | M | CM-001 | Offen |
| CM-003 | P1 | Veröffentlichte Fassung eindeutig belegen | M | CM-000 | Offen |
| CM-004 | P1 | Interessante Momente lokal analysieren | M | CM-003 | Offen |
| CM-005 | P1 | Alternative Auswahl im Vergleichsmodus | L | CM-004 | Offen |
| CM-006 | P1 | Vorschläge bewerten und evaluieren | M | CM-002, CM-005 | Offen |
| CM-007 | P2 | Facecam und Untertitel korrigieren | L | CM-003 | Offen |
| CM-008 | P2 | Technische Qualitätsprüfung | M | CM-003 | Offen |
| CM-009 | P2 | Betrieb, Wiederaufnahme und Diagnose | M | CM-000 | Offen |
| CM-010 | P2 | Speicherverwaltung und Sicherung | M | CM-003, CM-009 | Offen |
| CM-012 | P1 | Windows-Live-Highlights mit eigenem Dashboard und Upload | L | CM-000 | Zur Prüfung |

**Neue Priorität des Betreibers vom 20.11.2026: CM-012 (siehe unten), nach Korrektur des offenen PR #1. CM-001 bleibt im Backlog.**

**Bisheriger nächster Auftrag: CM-001. Die Basisauslieferung CM-000 ist geprüft und auf main veröffentlicht.** CM-003 kann danach vor CM-002 vorgezogen werden, falls keine echte Analytics-Abnahme möglich ist; Mock-Implementierung von CM-001 bleibt dennoch abschließbar. Konto-Abnahme als „Nicht verifiziert“ markieren.

## CM-000 – Öffentliche Übergabebasis

**Nutzen:** Ein unabhängiger Account kann ohne private Daten arbeiten.

**Ausgangspunkt:** Kein Git im ursprünglichen Projektordner, historisch widersprüchliche README, UI-Smoke-Test mit Verweisen auf echte Clips, getrennte Python-Umgebungen.

**Umfang dieser Lieferung:** Öffentliches Repo, MIT für eigenen Code, Drittanbieterhinweise, fixiertes Twitch-Submodul, README/Installation, Aufgabenliste, AGENTS.md, Startauftrag und PR-Vorlage. `clipmac.environment` trennt Datenverzeichnis und Entwicklungsmodus; `clipmac.dev` erzeugt synthetische Beispiele. Upload-/Auth-Sperren sitzen zusätzlich unterhalb der UI. CI und Veröffentlichungsscan hinzufügen. Importkonflikt mit Upstream-`tiktok_uploader.py` beheben.

**Abnahme:** Frische isolierte Testinstallation, vollständige Mock-Suite, API-Test des Entwicklungsmodus, synthetische Vorschau, JS-Syntaxcheck und Veröffentlichungsscan erfolgreich. Keine produktiven Dateien übernommen. Remote-Repo und CI prüfen. Abgenommen: 111 lokale Tests, 111 Tests im GitHub-macOS-Lauf, synthetische Browser-Vorschau und Veröffentlichungsscan. Basisauslieferung direkt auf main; Folgeaufgaben ausschließlich per PR. Belege unter `docs/VALIDIERUNG.md`.

## CM-001 – Optionale YouTube Analytics

**Ziel:** Wiedergabedauer und echtes Zuschauerverhalten ergänzen, nicht nur Views zählen.

**Ist-Zustand:** `clipmac/learning.py` verwendet YouTube Data API `videos.list`; gespeichert werden Views, Likes, Kommentare und Messzeitpunkte. `publisher.py` besitzt noch keinen Analytics-Scope.

**Arbeit:**

1. Eigenen Analytics-Adapter implementieren; bestehende Statistikmessungen und Uploadanmeldung unverändert nutzbar lassen.
2. Zusätzlichen OAuth-Scope `yt-analytics.readonly` nur über einen ausdrücklichen lokalen Verbindungsschritt anfordern. Fehlende Berechtigung ist ein sichtbarer Zustand, kein Grund, Uploads zu blockieren. Im Entwicklungsmodus nur synthetische Antworten.
3. Unterstützte Reports mit `reports.query`, `ids=channel==MINE` und eigener Videozuordnung abfragen. Zunächst `estimatedMinutesWatched`, `averageViewDuration`, `averageViewPercentage`, `shares`, `subscribersGained` und `engagedViews`, soweit die konkrete Kombination unterstützt wird. Retention als separater Einzelvideo-Report mit `elapsedVideoTimeRatio`/`audienceWatchRatio`.
4. Berichtszeitraum, Abrufzeit, Metrikdefinition, Plattform-Video-ID, Verfügbarkeit und Kanalzuordnung speichern. Tagesberichte niemals als exakten 1h-/2h-Snapshot deklarieren. Fehlende/unterdrückte Werte bleiben null mit Grund; keine Nullwerte erfinden.
5. Nach Aktivierung täglich zuletzt verfügbare 28 Tage aktualisieren; identische Berichtszeilen ersetzen statt summieren. Manuelle Aktualisierung rate-limitieren. Fehler mit begrenztem Backoff behandeln, Uploadpfad nicht blockieren.

**Komponenten:** neuer Analytics-Adapter, `learning.py`, `state.py`, `publisher.py`, Dashboard-API/UI.

**Tests/Abnahme:** Mock-Berichte mit Daten, Leerantwort, verzögerten Tagen, fehlendem Scope, fremder Kanal-ID, ungültiger Metrikkombination und Quota-Fehler. Keine Doppelsummen beim zweiten Abruf. Ohne Verbindung bleibt heutige Datensammlung funktionsfähig. Echte Verbindung und verfügbare Kennzahlen separat als geprüft/nicht geprüft dokumentieren.

**Quellen:** https://developers.google.com/youtube/analytics/channel_reports und https://developers.google.com/youtube/analytics/metrics . Schnittstellen vor Implementierung anhand dieser Primärquellen erneut prüfen. Keine Zusage, alle Studio-Kennzahlen über API zu erhalten.

## CM-002 – Vergleichbares Engagement-Dashboard

**Ziel:** Verständlich sehen, was beobachtet wurde und womit es vergleichbar ist.

**Ist-Zustand:** `performance_comparison()` vergleicht passende Stundenmessungen gegen einen einfachen Kanalmedian. Thema, Streamer und Länge werden noch nicht systematisch gruppiert.

**Arbeit:** Filter nach Plattform, Streamer, Kategorie, Veröffentlichungszeitraum, Videoalter und Länge. Längenklassen <30, 30–60, >60 Sekunden; fehlende Angaben separat. Stundenmessungen und Analytics-Berichte in getrennten Ansichten. Je Gruppe Stichprobengröße, Median und Datenstand anzeigen; Vergleiche unter fünf anderen passenden Videos als unzureichend kennzeichnen. Einzelvideo nicht in seinen eigenen Vergleich aufnehmen. Likes/Kommentare pro 100 Views inklusive Nenner erhalten. TikTok-Werte erst anzeigen, wenn tatsächlich erhoben; keine YouTube-Zahlen als TikTok-Erfolg darstellen.

**Komponenten:** `learning.py`, `learning-ui.js`, `learning.css`, Export.

**Tests/Abnahme:** Vergleich verschiedener Altersklassen verweigert; fehlende Werte nicht null; Division durch null sicher; kleine Kohorten sichtbar; spätere korrigierte Plattformwerte nachvollziehbar. Synthetische Dashboard-Vorschau mit guten, schwachen und nicht beurteilbaren Fällen. Formulierungen beschreiben Zusammenhänge, keine bewiesenen Ursachen.

## CM-003 – Veröffentlichte Fassungen eindeutig belegen

**Ziel:** Später wissen, welcher Schnitt und welcher Text wirklich gepostet wurden.

**Ist-Zustand:** `render_revision()` nutzt u. a. Dateigröße/mtime; `video_context()` kennzeichnet die Übereinstimmung mit Uploadfassungen ausdrücklich als nicht verifiziert. TikTok-Quittungen enthalten bereits SHA-256.

**Arbeit:** Gemeinsames unveränderliches Veröffentlichungsmanifest je Plattformversuch: Quelldatei-/Ausgabedatei-Hash, interne Clip-ID, Render-/Caption-Version, Modellname und verfügbarer Digest, tatsächlich verwendete Titel/Beschreibung/Tags, Versuch-ID, Zeitpunkte und bestätigte Plattform-ID. Manifest vor Versand schreiben, Ergebnis danach atomar ergänzen. Gleicher Inhalt bei geändertem mtime bleibt dieselbe Fassung; andere Bytes ergeben neue Fassung. Alte Datensätze behalten `unknown` statt nachträglicher Behauptungen. Keine Cookies/Tokens ins Manifest.

**Komponenten:** `learning.py`, `state.py`, `publisher.py`, TikTok-Quittungen, Export.

**Tests/Abnahme:** mtime-Änderung ohne Inhaltsänderung; gleiche Größe mit veränderten Bytes; Absturz vor/nach Versand; fehlende Datei; späterer Re-Render. Alte Bewertungen bleiben der ursprünglichen Fassung zugeordnet, bestehende Sperren erhalten.

## CM-004 – Interessante Momente lokal analysieren

**Ziel:** Begründete redaktionelle Hinweise statt pauschalem „Viralitätsscore“.

**Ist-Zustand:** Transkript und Wortzeiten existieren. Titelerzeugung verwendet hauptsächlich Originaltitel/Kategorie; kein Moment-Ranker und kein Training.

**Arbeit:** Nach Transkription optional lokale Ollama-Inferenz mit vorhandener Modellkonfiguration. Strukturiertes Ergebnis zu Einstieg, Reaktion, möglicher Pointe und fehlendem Kontext. Jede Behauptung braucht passende Transkriptbelege mit Start/Ende innerhalb des Clips. Reine visuelle Aussagen nicht aus Text erfinden. Ergebnis kann „nicht beurteilbar“ sein. JSON validieren, Timeout und maximale Antwortgröße setzen, kaputte Antworten als fehlgeschlagen speichern. Transkriptinhalt als Daten behandeln, nicht als Instruktionen. Ergebnisse nach Medien-/Transkripthash, Promptversion und Modellidentität zwischenspeichern.

**Komponenten:** neuer Momentanalyse-Dienst, bestehende Transkript-/Metadatenpfade, `state.py`, Dashboard.

**Tests/Abnahme:** synthetische Dialoge mit klarer Reaktion, ohne Pointe, ohne Sprache, widersprüchlicher Modellantwort, Prompt-Injection im Transkript, ungültigen Zeitmarken und Timeout. Keine neuen Uploads, keine Gewichtsänderungen. Modelltexte klar als Vorschläge kennzeichnen. Ohne Ollama bleibt die bisherige Pipeline nutzbar.

## CM-005 – Alternative Auswahl im Vergleichsmodus

**Ziel:** Prüfen, ob lokale Analyse eine bessere Auswahl unterstützt.

**Ist-Zustand:** `content_policy.ranked_pool()` und `select_clips()` sortieren nach Twitch-Aufrufen und deduplizieren. Kein alternatives Ranking.

**Arbeit:** Separater manueller „Auswahl vergleichen“-Auftrag: maximal zehn nach Aufrufen vorselektierte passende Clips je Streamer, bestehende Kategorie-/Zeit-/Überlappungssperren anwenden. Fehlende Kandidaten lokal herunterladen/transkribieren, seriell und abbrechbar; keine Einschleusung in Uploadjobs. Baseline und alternative Top fünf aus demselben Kandidatenpool speichern. Für v1 bewerten lokal erzeugte Kriterien Einstieg, Kontextverständlichkeit und belegter Höhepunkt jeweils 0–2; Summe als heuristische Redaktionshilfe, bei Gleichstand Twitch-Rang. Unbelegte Kriterien bleiben unbekannt, solche Clips erhalten keine erzwungene Gesamtwertung. Gewichtung/versionierte Regeln dokumentieren, nicht als trainiertes Modell bezeichnen. Ausgewählte Zeitmarken sind Hinweise, keine automatische Neumontage.

**Komponenten:** separate Analysequeue/-tabelle, CM-004, Discovery-/Policy-Helpers, Dashboard-Fortschritt.

**Tests/Abnahme:** maximal zehn pro Streamer; Abbruch zwischen Arbeitsschritten; Cachetreffer; deduplizierte Kandidaten; abgelaufene/gesperrte Clips; fehlende Transkripte. Kein Aufruf von YouTube/TikTok-Publishing. Produktive Paketreihenfolge unverändert. Dauer und lokale Ressourcen pro analysiertem Clip erfassen.

## CM-006 – Vorschläge bewerten und evaluieren

**Ziel:** Messbare Grundlage dafür, ob das neue Verfahren nützt.

**Arbeit:** Paarvergleich zweier Vorschläge mit A/B-Reihenfolge zufällig, optional ausgeblendeter Herkunft. Auswahl A, B, gleichwertig oder nicht beurteilbar plus kurze Begründung. Bewertungen an Version und Belege binden; Änderungen als Verlauf erhalten. Bevorzugungsrate, Anzahl eindeutiger Vergleiche und Unsicherheit ausgeben. Technische Schnittfehler getrennt halten. Spätere Plattformzahlen nur bei bestätigter Veröffentlichungszuordnung aus CM-003 ergänzen. Nicht veröffentlichte Kandidaten besitzen keine beobachtete YouTube-Performance: fehlende Gegenfakten nicht erfinden.

**Komponenten:** neue Paarvergleichs-UI, versionierte Labels/Exporte, Auswertungsskript mit synthetischem Beispieldatensatz.

**Tests/Abnahme:** Seitenwechsel erzeugt keine vertauschten Labels; Unentschieden/Enthaltungen nicht als Niederlagen; keine Vermischung mehrerer Fassungen; kleine Stichproben ausdrücklich unsicher. Vor späterem Training nach VOD/überlappenden Segmenten gruppieren und zeitlich aufteilen; keine identischen Stellen in Training und Test. Hier noch kein Training und keine automatische Auswahlumstellung. Kontrollierte Posting-Experimente nur als gesondertes Konzept beschreiben.

## CM-007 – Facecam und Untertitel korrigieren

**Ziel:** Sichtbare Schnittfehler im Dashboard direkt korrigieren.

**Arbeit:** Originalvorschau mit verschiebbarem normiertem Facecam-Rechteck; Split-/Fullcam-Modus abschnittsweise überschreiben. Untertiteltext pro vorhandenem Wortzeitbereich bearbeiten, Original erhalten. Änderungen als neue Renderrevision speichern, lokale Vorschau erzeugen. Zeiten/Bildgrenzen validieren. Korrektur vor Upload auf eine noch nicht versandte Fassung anwenden; bereits veröffentlichte Beiträge niemals automatisch ersetzen oder erneut posten. Neue Fassung braucht neue Bewertung.

**Komponenten:** Galerie/Vorschau, Layout-Timeline, Captions, Renderqueue, CM-003.

**Tests/Abnahme:** ungültige Rechtecke, Wechsel zwischen Formaten, lange Wörter, Sonderzeichen, bestehende offene Meldungen, gleichzeitiger Uploadversuch. Original bleibt erhalten; Vorschau zeigt genau neue Fassung; keine stillschweigende Übertragung alter Labels. Gute Referenzclips nach Korrektur weiterhin prüfen.

## CM-008 – Technische Qualitätskontrolle vor Upload

**Ziel:** Offensichtlich defekte Ausgaben zuverlässig anhalten.

**Arbeit:** Versionierten Qualitätsbericht je Renderrevision erzeugen: decodierbare Video-/Audiospur, erwartete Abmessungen/Dauer, gültige Wortzeiten, Text innerhalb Layoutgrenzen und gültige Crops. Eindeutige technische Fehler blockieren nur den betroffenen Clip; unsichere Facecam-Einschätzung als Warnung/Prüfbedarf ausweisen. Kein Gesicht gefunden bedeutet nicht automatisch Defekt. Prüfergebnisse und Gründe im Dashboard anzeigen und vor Upload auf aktuelle Revision prüfen.

**Komponenten:** `media.py`, `captions.py`, `layout.py`, Uploadreservierung, Dashboard.

**Tests/Abnahme:** beschädigte Datei, fehlender Ton, schwarzes synthetisches Video als Warnfall, Textüberlauf, Clip ohne Kamera, legitime Fullcam. Prüffälle je Fehler, keine pauschale Blockade guter Referenzclips. Qualitätssignal nicht mit Reichweite verrechnen.

## CM-009 – Betrieb, Wiederaufnahme und Diagnose

**Ziel:** Fehler verständlich erkennen und nach Unterbrechungen ohne Doppelposts fortsetzen.

**Arbeit:** Explizite Zustände für fehlende Modelle/Tools, abgelaufene Anmeldung, Kanal-/Projektlimit, Browserprüfung, unklaren Upload und Stundenpause. Fehlermeldungen mit nächstem sinnvollen Schritt statt Roh-Tracebacks. Backoff begrenzen, Uploadunsicherheit niemals automatisch wiederholen. Diagnoseexport ohne Tokens, Cookies, Originaltexte oder private Pfade. Abhängigkeiten, verfügbare Modell-Digests, Schrittzeiten und freier Speicher lokal erfassen. Für Hintergrundthreads unerwartete Fehler protokollieren statt stilles Sterben. Bestehende Prozesslocks/Transaktionen erhalten.

**Komponenten:** Engine, Publisher, TikTok-Controller/Worker, Launch, Dashboard.

**Tests/Abnahme:** Crash vor Versand, nach Versand ohne Quittung, Quota-Pause über Neustart, veralteter Clip nach Pause, erneuter Login nötig, Thread-Ausnahme, zwei gleichzeitige Starts. Keine doppelten Reservierungen/Postings. Diagnosedaten mit Secret-Fixtures prüfen. Ein synthetischer Dauertest dokumentiert mehrere Jobs und Wiederaufnahme.

## CM-010 – Speicherverwaltung und portable Sicherung

**Ziel:** Wachsenden Speicherverbrauch kontrollieren und Updates rückgängig machen können.

**Arbeit:** Verbrauch nach Originalen, Zwischenständen, finalen Videos und Modellen anzeigen. Standard: keine automatische Löschung. Optionale Aufbewahrung erst nach Konfiguration; Vorschau der betroffenen Dateien und Größe. Dateien aktiver Jobs/offener Meldungen sowie Quittungen, Veröffentlichungsmanifeste und Löschsperren ausnehmen. Nur kanonisch innerhalb des konfigurierten Datenordners liegende Dateien bearbeiten; Symlinks nicht außerhalb verfolgen. Lokales Backup mit konsistentem SQLite-Snapshot und Manifest; Restore in neuen Ordner prüfen, bestehende Installation nicht überschreiben. Credentials standardmäßig aus portablen Exporten ausschließen, fehlende Kontoverbindung nach Restore erklären.

**Komponenten:** Datenablage, neuer Wartungsdienst, Dashboard, Installationsdokumentation.

**Tests/Abnahme:** Symlink-Ausbruch, Pfadtraversal, paralleler Render, offener Fehlerbericht, wenig Speicher, unterbrochene Sicherung, beschädigtes Backup und Restore. Nach Restore bleiben bekannte/veröffentlichte/gelöschte Clips gesperrt. Trockene Vorschau stimmt mit tatsächlichem Umfang überein.

## Weitere Überlegungen – vorerst nicht implementieren

- **Modell-Provenienz/Lizenz:** Exakte Digests und Revisionen statt beweglicher Tags festhalten. Qwen2.5-3B-Instruct ist nicht pauschal Apache-2.0; Modellkarte nennt qwen-research. Kommerzielle Verwendung separat prüfen; kein Modelltausch ohne Qualitätsvergleich.
- **Visuelles Verständnis:** Eine spätere lokale Bildanalyse könnte textlose Reaktionen erkennen. Erst Laufzeit/RAM am Ziel-Mac messen und gegenüber der Text-Baseline evaluieren.
- **Bessere Titel:** Belegte Transkriptstellen könnten die derzeit vorsichtige Titelvorlage verbessern. Erst Entwürfe vergleichen; keine erfundenen Zitate, Namen oder Clickbait-Versprechen.
- **Mehr Engagement-Messung:** TikTok-Daten erst über eine tatsächlich verfügbare, legitim angebundene Quelle ergänzen. Keine Interaktionen automatisiert erzeugen.
- **Professionalisierung:** Plattformübergreifende Installation, Modell-/Dependency-Hashes, UI-Barrierefreiheit und echte End-to-End-Renderbenchmarks. Remote-Dashboard braucht ein eigenes Authentifizierungs-/Betriebskonzept und ist nicht Teil dieses Auftrags.


## CM-012 – Windows-Live-Highlights mit eigenem Dashboard und Upload

**Verbindliche Änderung vom 20.11.2026:** Diese Fassung ersetzt vollständig die frühere CM-012-Spezifikation. Bereits begonnene A/B/C-Branches daran anpassen. Neue Zielplattform ausschließlich Windows; keine Live-Überwachung auf dem Mac. Bestehende Mac-Top-Clip-Pipeline bleibt ein unabhängiges System. Aufgabe umfasst Implementierung als PRs, nicht nur Recherche.

### Architektur und Grenzen

- Eigenständige Windows-Anwendung im selben Repository, eigener Einstiegspunkt, eigener lokaler Dashboard-Server, eigene SQLite-Datenbank, Aufnahmeordner, OAuth-Tokens und TikTok-Browserprofil. Keine gemeinsam geöffnete SQLite-Datei, kein Dateitransfer, keine Mac-API und kein Abgleich mit Mac-Veröffentlichungen. GitHub dient nur dem Quellcodeaustausch.
- Zwei auswählbare Twitch-Livestreams gleichzeitig überwachen. Auswahl aus bestehenden vier Streamern; keine zusätzlichen fest verdrahteten Namen. Offline-Kanäle alle 60 Sekunden prüfen. Benutzer startet/stoppt den Windows-Auftrag im Dashboard; der PC muss wach bleiben. Kein dauerhaft sichtbarer Browserplayer nötig.
- Windows nativ unterstützen: kein ungeprüfter Import von `fcntl`, keine macOS-Pfade, `caffeinate`, `say` oder `Meta+A` voraussetzen. Plattformneutrale Bibliotheken und passende Windows-Prozesslocks, Browser-Tastaturkürzel und Systemschriften verwenden. Gemeinsame reine Schnitt-/Score-Helfer dürfen wiederverwendet werden; bestehende Mac-Einstiegspunkte nicht auf Windows umbiegen.
- Rechenarbeit lokal: FFmpeg/Streamlink, Whisper, Ollama. Keine Codex-/Cloud-KI-Dauerschleife. Ein Render-/Analyseworker, zwei Recorder; Pufferaufzeichnung darf durch Rendering nicht blockieren.
- Kein geräteübergreifender Duplikatabgleich gewünscht. Trotzdem lokale Wiederholungen desselben Windows-Uploadauftrags verhindern: lokale Versuch-ID und Plattformquittung, damit ein Timeout keinen zweiten identischen Post auslöst. Das ist Transaktionssicherheit, keine Recherche der vorhandenen Kanalvideos.
- GTA-6-Kategorie bleibt als bisherige Inhaltsvorgabe erhalten; während der Aufnahme prüfen. Die Mac-Regeln Top fünf/letzte sieben Stunden/Fünferpakete sind keine gemeinsame Windows-Queue. Windows erstellt frische Live-Highlights und veröffentlicht sie nach Eignungsprüfung; keine künstliche Auffüllung einer Clipanzahl und keine Synchronisierung der Postingzeiten mit dem Mac.

### A – Live-Momente erkennen

- Fünf Minuten Ringpuffer je Stream, fünfsekündige Segmente. Kandidaten reservieren Vor-/Nachlauf, alte unreservierte Segmente automatisch aufräumen. Insgesamt 5 GB Pufferlimit; unter 5 GB freiem Datenträgerspeicher geordnet pausieren und Warnung zeigen.
- Aktuell unterstützten Twitch-Chatzugang implementieren und Rechte dokumentieren. Chat lesen, keine Nachrichten senden. Standardmäßig nur aggregierte Aktivität speichern, keine dauerhafte Rohchat-/Nutzerhistorie.
- V1-Spike-Detektor: 10-Sekunden-Fenster, 180 Sekunden vorherige Baseline ohne aktuelles Fenster. Nach Warmup mindestens 15 Nachrichten von fünf unterschiedlichen Teilnehmern, mindestens dreifache normale Nachrichtenrate und robuste Abweichung von mindestens drei MAD; Nenner jeweils mindestens 1. Wiederholungen eines Nutzers begrenzen. Konfigurierbare Startwerte, kein behauptetes Modelltraining. Verbindungsabbrüche als Datenlücke behandeln, danach neu aufwärmen.
- Empfangszeiten auf Medienzeit abbilden. Konfigurierbarer Reaktionsversatz zunächst sechs Sekunden; Fenster zunächst 30 Sekunden davor und danach. Nahe Ereignisse innerhalb 60 Sekunden zusammenführen, maximal 120 Sekunden. Fehlender Kontext, unbekannte Kategorie oder gemischte Streamsitzungen dürfen nicht automatisch freigegeben werden.

### B – Sinnvoll schneiden und Eignung bewerten

- Aus längeren Live-Passagen zusammenhängende Highlights erstellen: verständlicher Einstieg, Kontext vor dem Höhepunkt, vollständige Sätze und Abschluss/Reaktion. Ziel 20–60 Sekunden, höchstens 120 Sekunden bei benötigtem Kontext. Nicht nur nach starren Sekunden oder Lautstärke schneiden. Bestehende Wortuntertitel, Facecam-Drittel und Fullcam-Wechsel wiederverwenden und auf Windows prüfen.
- Lokales Transkript mit Wortzeiten; bei langen Quellen in 10-Minuten-Blöcken mit 30 Sekunden Überlappung arbeiten und Zeitmarken deduplizieren. Die vorhandene Kurzclip-Längenprüfung nicht global entfernen. Separater VOD-/Dateiimport ist nachrangig und darf die Windows-Live-Version nicht blockieren; Altvideos standardmäßig nicht automatisch veröffentlichen.
- „Viral Score (experimentell)“ 0–100 als Redaktionshilfe, keine Erfolgswahrscheinlichkeit. V1: Chat-Stärke 20 %, Teilnehmerbreite 15 %, Einstieg 20 %, Kontext 20 %, Höhepunkt/Abschluss 25 %. Chat-Werte relativ zur eigenen Baseline: 1×→0, 5×→100, dazwischen linear/begrenzt. Lokales LLM liefert Textkriterien 0/1/2 mit echten Zeitbelegen; diese auf 0–100 skalieren. Fehlende Signale oder ungültige Modellantwort → keine automatische Freigabe. Keine automatische Gewichtsänderung/Trainingspipeline.
- Standard „lohnt sich“: bestätigter Chat-Spike, vollständiger Live-Score mindestens 70, Kontext und Abschluss jeweils mindestens 1/2, bekannte passende Kategorie und alle technischen Prüfungen bestanden. Schwelle im Dashboard einstellbar. Das sind konservative v1-Startwerte ohne empirische Erfolgsgarantie. Unterhalb der Schwelle lokal ablegen/überspringen, keine Uploadquote auffüllen.
- Technische Prüfungen: decodierbare Bild-/Tonspuren, gültige Ausschnitte und Untertitelzeiten, keine abgeschnittenen Texte, plausible Dauer und A/V-Synchronität. Schnittfassung, Herkunft und Score-Version speichern. Begründungen intern für Diagnose, keine verpflichtende Erklärungsansicht im Dashboard.

### C – Eigenständig auf TikTok und YouTube veröffentlichen

- Windows lädt geeignete Highlights selbst hoch, TikTok zuerst und anschließend YouTube. Beide Plattformen im Normalbetrieb aktiv; getrennte Verbindung/Startfreigabe im Dashboard. Keine manuelle Freigabe jedes geeigneten Clips erforderlich, sobald der Nutzer die Windows-Automatik aktiviert hat. Dies ersetzt für CM-012 ausdrücklich die frühere Vorgabe „nur vergleichen“.
- Eigene Kontoanmeldung auf Windows; keine Cookies/Tokens vom Mac oder über GitHub übertragen. Vor Upload Zielkonto bestätigen. Zielkonten lokal konfigurieren, keine privaten Daten ins öffentliche Repo. Bestehende Uploadlogik soweit plattformneutral wiederverwenden, Windows-Anpassungen separat testen.
- Pro Plattform eigene persistente Zustände: wartet, lädt hoch, übermittelt/in Prüfung, öffentlich bestätigt, fehlgeschlagen, Ergebnis unklar. TikTok-Fehler dürfen einen ansonsten zulässigen YouTube-Upload nicht dauerhaft blockieren; erfolgreiche Plattform nicht erneut bedienen, wenn nur die andere wiederholt wird.
- Automatisch weiterarbeiten, solange Aufnahme/Upload aktiviert ist. Plattformlimits, Quotas, Loginprobleme und CAPTCHAs respektieren und sichtbar pausieren; kein Umgehen von Plattformprüfungen. Unklarer Versand wird nicht blind wiederholt. Stop verhindert neue Aufgaben und neue Posts; bereits übermitteltes Ergebnis noch zuordnen.

### Dashboard – bewusst einfach und passend zu Windows

- Breite Desktop-Oberfläche: oben genau zwei Streamkarten mit Kanalname, live/offline/verbunden, Chat-Aktivität, Aufnahmestatus, Start/Stopp. Darunter Clipgalerie und kompakter Arbeitsfortschritt.
- Je Clip Thumbnail, Streamer, Zeitpunkt, Dauer, Score und abspielbare **fertige Schnittfassung**. Optional „Originalausschnitt“ zum Vergleich; Schnittanfang/-ende sichtbar. Ein Thumbnail allein erfüllt die Schnittvorschau nicht.
- Zwei separate Plattformfelder mit Videolink: TikTok und YouTube. Grünes Häkchen erst bei bestätigter öffentlicher Veröffentlichung. Bei TikTok-Moderation ausdrücklich „In Prüfung“, bei unklarem Ergebnis „Prüfen“. Niemals einen erfolgreichen API-/Formularversand als bestätigte Öffentlichkeit ausgeben.
- Fehler mit kurzer Handlungsempfehlung, Fortschritt von Erkennung→Analyse→Schnitt→Upload. Keine unnötige Erklärungspflicht, Diagrammflut oder Volltext-Chatansicht.

### Referenzen und Herkunft

- https://github.com/st1fo/stream-clipper/tree/70ec4edc1f27be062ad1a4822aa87b84f8d5f85e : README beschreibt Ringpuffer, Chat-Spikes und VOD-Auswahl; Architekturreferenz, nicht auf unserem Windows-PC verifiziert.
- https://github.com/Higuy3000/twitch-clipbot/tree/3431055027862565bfb903185088d36047cdd00f : Referenzmodule `chat.py`, `detector.py`, `recorder.py`, `clipper.py`, `retention.py`.
- Bei Recherche keine von GitHub erkannte Lizenz. Vor jeder Übernahme konkrete Lizenz prüfen; ohne Erlaubnis keine Codekopie. Geeignete lizenzierte Bibliotheken verwenden und Funktion eigenständig implementieren. Keine fremden Installer ungeprüft ausführen.

### Abnahme / Lieferung

1. Windows-CI und dokumentierter frischer Windows-Start ohne macOS-Abhängigkeiten. Bestehende Mac-Tests weiterhin grün. Entwicklungsmodus mit synthetischen Streams und Fake-Uploadern, produktive Netz-/Uploadaktionen standardmäßig gesperrt.
2. Zwei synthetische Streams gleichzeitig: normale Aktivität, echter Burst, Spam, stille Baseline, Reconnect und Kategorie-Wechsel. Kontextreservierung, Zusammenführung, Zeitversatz und keine Vermischung zwischen Kanälen prüfen.
3. Synthetische lange Quelle: Höhepunkt an Blockgrenze, Satzanfang/-ende erhalten, Wortzeiten nach Kürzung korrekt, A/V-Längendifferenz aus PR #1 als Regression. Abspielbare Original-/Schnittvorschau auf Windows zeigen.
4. Eignung: schlechte/unklare Kandidaten nicht posten; geeignete automatisch an beide Fake-Plattformen. Fehlender Chat/LLM-Ausfall darf keine Freigabe erzeugen. Persistente Score-Version und Belege.
5. Uploadfälle: TikTok erfolgreich/YouTube fehlgeschlagen und umgekehrt, Moderation, unklarer Ausgang, Quota, Neustart, Stop und erneute Anmeldung. Plattformstatus wahrheitsgemäß; keine Wiederholung bereits bestätigter Windows-Uploads. Kein Mac-Abgleich und keine Übertragung zum Mac.
6. Zwei-Stream-Probelauf: CPU/RAM, Pufferverbrauch, Verarbeitungsdauer und Warteschlangenwachstum messen. Speicherlimit, fehlende Segmente und Prozessabsturz testen. Tatsächliche Windows-/Live-/Konto-Abnahme getrennt von Mock-Belegen dokumentieren.

**Lieferung:** Bestehende CM-012-A/B/C-PRs an diese Vorgaben anpassen: A = Windows-Recorder und Chat, B = Schnitt/Eignung, C = eigenes Dashboard und getrennte Windows-Uploader. Nach überprüfbarer Implementierung und lokaler Kontoeinrichtung soll die Windows-App unabhängig vom Mac arbeiten. Keine Installation oder Aktivierung der Live-Überwachung auf dem Mac.

**Umsetzungsstand CM-012 (Windows, Zur Prüfung):** Paket `clipmac_windows` mit eigenem Einstieg `python -m clipmac_windows`, Dashboard auf 127.0.0.1:8765, eigener SQLite-Datei und Datenordner unter `%LOCALAPPDATA%`. A = Recorder/Chat (`live_capture`, `live_chat`, `live_buffer`), B = Schnitt/Eignung (`analysis_core`, `pipeline`, `render`, `scoring`, `llm`), C = Dashboard/Uploader (`engine`, `server`, `static/`, `uploaders`, `queue`). Startanleitung: `docs/WINDOWS.md`. Belegt nur mit synthetischen Streams und simulierten Uploads; echte Twitch-/Konto-/Upload-Abnahme und Zwei-Stream-Lastlauf mit echten Streams stehen aus.

