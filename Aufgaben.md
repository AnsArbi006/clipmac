# ClipMac – Arbeitsaufträge für die Weiterentwicklung

Stand: 19.11.2026. Diese Liste beschreibt **offene Arbeit**, nicht bereits vorhandene Funktionen. Schwerpunkt: Engagement verstehen und interessante Momente erkennen. Der zweite Account bearbeitet jeweils **eine Aufgabe pro Pull Request** in dieser Entwicklungskopie.

## Verbindliche Entscheidungen

- Nur lokale KI-Inferenz; keine kostenpflichtigen KI-APIs. Gegenwärtig keine eigene Trainingspipeline.
- Neue Rankings zunächst nur zum Vergleich. Die produktive Auswahl bleibt nach Twitch-Aufrufen, bis der Betreiber eine Umstellung ausdrücklich beauftragt.
- Vier Streamer im GTA-6-Profil, sieben Stunden Aktualität, Top fünf pro Streamer, Pakete bis fünf mit mindestens 60 Minuten Pause. Keine stillen Änderungen daran.
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


## CM-012 – Live-Highlights, Viral Score und sinnvolle Langvideo-Schnitte

**Status:** Zur Prüfung. **Priorität:** P1, neuer ausdrücklicher Nutzerauftrag vom 20.11.2026. **Aufwand:** L; in die unten definierten Teil-PRs aufteilen. Erst den offenen Schnittfehler in PR #1 korrigieren. CM-004/005 liefern verwandte Anforderungen und werden durch diese Umsetzung ergänzt, nicht doppelt gebaut. CM-003-Fassungszuordnung für neue Ergebnisse mit berücksichtigen.

### Auftrag an den zweiten Account

Implementiere eine neue integrierte MacClip-Funktion, die Twitch-Livestreams während ihrer Laufzeit überwacht, Chat-Spitzen erkennt, den davor liegenden Kontext aufbewahrt und daraus sinnvoll geschnittene Hochformat-Highlights mit Wortuntertiteln erstellt. Ergänze dieselbe Highlight-Auswahl für lange lokale Videos und Twitch-VODs. Liefere funktionierende Codeänderungen, Tests und Dashboard-Bedienung als Pull Requests; eine Recherche oder ein Konzept allein erfüllt diesen Auftrag nicht. Lokale KI, keine kostenpflichtige Cloud-Inferenz.

### Konkrete Referenzrepos

- Hauptreferenz: https://github.com/st1fo/stream-clipper/tree/70ec4edc1f27be062ad1a4822aa87b84f8d5f85e . README beschreibt Live-Ringpuffer und Chat-Erkennung sowie einen VOD-Modus. Relevante Bereiche sind `stream_clipper/`, `config/` und `tests/`. Als Architekturreferenz lesen; weder Funktionsfähigkeit auf unserem Mac noch Qualität der Scores wurde hier getestet.
- Kleine ergänzende Referenz: https://github.com/Higuy3000/twitch-clipbot/tree/3431055027862565bfb903185088d36047cdd00f . Einstiegspunkte: `clipbot/chat.py`, `detector.py`, `recorder.py`, `clipper.py`, `retention.py`. Beschreibt ebenfalls Aufnahme und Chat-getriggerte Clips.
- Bei beiden Repositories meldete GitHub am Recherchezeitpunkt keine erkannte Lizenz. Vor Codeübernahme Lizenz und konkrete Revision prüfen und Herkunft dokumentieren. Ohne passende Erlaubnis keine Dateien/Codefragmente übernehmen; Funktion eigenständig auf Basis geeigneter lizenzierter Bibliotheken wie Streamlink/FFmpeg und der Twitch-Schnittstellen implementieren. Keine fremden Installationsskripte ungeprüft ausführen.

### Teil-PR A: Live-Aufzeichnung und Spike-Erkennung

- Dashboard: eigener Bereich „Live-Highlights“, vier bestehende Streamer, pro Kanal Start/Stopp, offline/verbunden/wärmt auf/zeichnet auf/Fehler, Pufferdauer und belegter Speicher. Standard deaktiviert, kein Autostart nach Installation. Offline-Kanäle alle 60 Sekunden prüfen. Der Mac muss wach und der Prozess aktiv sein; kein dauerhaft offener Browserplayer nötig.
- Streamlink/FFmpeg in einen lokalen 5-Minuten-Ringpuffer mit 5-Sekunden-Segmenten aufnehmen. Nur ausgewählte Kanäle; zuerst maximal zwei gleichzeitige Recorder, weitere sichtbar wartend. Alte unreservierte Segmente entfernen; Kandidaten reservieren benötigte Segmente bis zum abgeschlossenen Export. Insgesamt maximal 5 GB Live-Puffer; bei weniger als 5 GB freiem Speicher Aufnahme geordnet pausieren und warnen, niemals aktive Segmente löschen.
- Twitch-Chat über aktuell unterstützte Schnittstelle lesen. Authentifizierung, notwendige Rechte und Wiederverbindung dokumentieren; keine nicht verifizierte anonyme Zugangsmöglichkeit voraussetzen. Keine Chatnachrichten senden. Nachrichten zählen, unterschiedliche Teilnehmer pro Zeitfenster erkennen; Nutzerkennungen nur flüchtig, standardmäßig keine Rohtexte dauerhaft speichern.
- Eigenständiger v1-Detektor: 10-Sekunden-Fenster, vorherige 180 Sekunden als Baseline ohne aktuelles Fenster. Trigger erst nach Aufwärmphase: mindestens 15 Nachrichten und fünf unterschiedliche Teilnehmer, Nachrichtenrate mindestens dreimal Baseline (Nenner mindestens 1 Nachricht/Fenster), zusätzlich robuste Abweichung mindestens drei MAD mit Nenner mindestens 1. Schwellen konfigurierbar; diese Startwerte sind Heuristiken, kein trainiertes Modell. Wiederholungen desselben Nutzers begrenzen. Disconnects zählen als Datenlücke, nicht als ruhiger Chat.
- Zeitbasis: Empfangszeiten und Medien-PTS zuordnen; Chat-Reaktionsversatz zunächst konfigurierbare 6 Sekunden. Kandidat zunächst 30 Sekunden vor bis 30 Sekunden nach korrigiertem Trigger. Nahe Ereignisse innerhalb 60 Sekunden zusammenführen, maximal 120 Sekunden. Bei fehlendem Vorlauf sichtbar als unvollständig markieren. Nach Reconnect neu aufwärmen. Keine Überschneidung verschiedener Streamsitzungen.
- Kategorie während der Aufnahme prüfen und mit Segmentzeiten speichern. Bestehender GTA-6-Filter bleibt verbindlich; unbekannte oder wechselnde Kategorie im Kandidaten führt zu Prüfbedarf, nicht stiller Freigabe.

### Teil-PR B: Lange Videos und sinnvolle Schnittgrenzen

- Import einer lokalen Datei oder einer expliziten Twitch-VOD-URL, abbrechbarer Analyseauftrag mit Fortschritt. Lange Quellen separat verarbeiten: die bisherige 190-Sekunden-Grenze von `cut_silence()` nicht pauschal entfernen. Stattdessen abschnittsweise mit 30 Sekunden Überlappung transkribieren, absolute Zeitmarken erhalten und deduplizieren; zunächst 10-Minuten-Analyseblöcke, ein CPU-Analyseworker.
- Aus Chat-Ereignissen, Transkript und optional lokaler Audioenergie Kandidaten vorschlagen. Ohne Chat Datenbasis sichtbar kennzeichnen. Reine Lautstärke oder Emotes nicht automatisch als Humor klassifizieren.
- Lokales Ollama prüft verständlichen Einstieg, erforderlichen Kontext, Reaktion/Höhepunkt und Abschluss. Jede Aussage braucht Zeitmarken und Transkriptbelege. Fehlende Evidenz ergibt „nicht beurteilbar“; keine erfundenen Handlungen. Ungültiges JSON/Timeout begrenzt behandeln.
- Ziel 20–60 Sekunden; bis 120 Sekunden, wenn der Sinn es erfordert. An tatsächlichen Satz-/Pausengrenzen schneiden, Kontext vor der Pointe erhalten und Reaktion auslaufen lassen. Keine Satzhälften nur wegen eines Längenziels abschneiden. Zunächst zusammenhängende Ausschnitte, keine Umstellung der Chronologie und keine erfundenen Hooks. Innenpausen vorsichtig kürzen; relevante stille Bildmomente zur Prüfung markieren.
- Vorhandene Facecam-/Fullcam-Pipeline und Wortuntertitel wiederverwenden. Original, Zeitzuordnung, Schnittfassung und Begründung speichern. Bereits veröffentlichte Dateien unverändert lassen.

### Teil-PR C: Viral Score und Vorschau

- Anzeige „Viral Score (experimentell)“ von 0–100; ausdrücklich keine Erfolgswahrscheinlichkeit und kein Nachweis von Viralität. Einzelwerte und Gründe anzeigen: Chat-Spitze, Vielfalt reagierender Teilnehmer, Einstieg, Kontextverständlichkeit, Höhepunkt/Abschluss.
- Versionierte v1-Gewichte: Chat-Stärke 20 %, Teilnehmerbreite 15 %, Einstieg 20 %, Kontext 20 %, Höhepunkt/Abschluss 25 %. Textkriterien lokal als 0/1/2 mit Belegen beurteilen und auf 0–100 skalieren. Chat-Stärke aus Verhältnis zur Baseline: 1×→0, 5×→100, dazwischen linear und begrenzt. Teilnehmerbreite analog gegenüber der eigenen historischen Teilnehmer-Baseline. Keine absoluten Vergleiche großer und kleiner Streamer.
- Fehlender Chat darf nicht als null eingehen. Bei VOD ohne Chat separate textbasierte Wertung mit normalisierten verfügbaren Gewichten und Kennzeichnung „ohne Chat“; nicht mit vollständigem Live-Score in eine gemeinsame Rangliste mischen. Bei fehlenden Textbelegen keine Gesamtwertung erzwingen. Technische Fehler separat sperren, nicht durch guten Score kompensieren.
- Kandidatenkarten mit Vorschau, Score-Aufschlüsselung, Quellenzeit, vorgeschlagenem Schnitt und Gut/Mittel/Schlecht sowie Fehlerbericht. Ab 60 Punkten standardmäßig als empfohlen markieren, ohne automatisch zu veröffentlichen. Schwelle lokal konfigurierbar, Modell-/Prompt-/Score-Version speichern.
- Die bisherige Entscheidung „erst vergleichen“ gilt weiter: neuer Live-/VOD-Pfad erzeugt zunächst Review-Kandidaten. Freigegebene aktuelle Live-Kandidaten dürfen über eine bewusste Dashboard-Aktion in die bestehende Paketqueue; keine neue parallele Uploadfunktion. Ältere VOD-Highlights bleiben lokal, da sie die bestehende Sieben-Stunden-Regel nicht erfüllen. Vor Upload alle bisherigen Kategorie-, Alters-, Sperr- und Duplikatregeln erneut prüfen.
- Für Live-/VOD-Kandidaten Herkunft und ID sauber modellieren: Stream-ID/VOD-ID plus Zeitintervall und Medienhash; keine erfundenen Twitch-Clip-IDs. Doppelte/überlappende Ausschnitte auch gegenüber bereits bekannten Twitch-Clips abgleichen, soweit VOD-Zuordnung vorhanden; unklare Herkunft kennzeichnen. Datenmodell und Paketadapter additiv migrieren.

### Abnahme und Tests

1. Synthetischer Chat: normale Rate, echter Burst vieler Teilnehmer, Spam eines Nutzers, dauerhaft großer Chat, stille Baseline, Reconnect, verzögerte Nachrichten. Trigger, Warmup und Zusammenführung deterministisch testen.
2. Synthetische segmentierte Aufnahme: Vor-/Nachlauf, fehlende Segmente, Chatversatz, Kategorie-Wechsel, voller Datenträger, Stop während Aufnahme/Export und Neustart. Keine Endlosqueues oder unkontrolliert wachsende Dateien.
3. Langes synthetisches Video mit Pointe an einer Blockgrenze: Kontext und Abschluss im selben Short, absolute Wortzeiten korrekt, keine doppelten Highlights. A/V-Längendifferenz aus PR #1 als Regression erhalten.
4. Score: fehlende Signale, ungültige Modellantwort, Prompt-Injection aus Chat/Transkript, Grenzwerte, nachvollziehbare Gewichtung und Versionsänderungen. Keine fehlenden Kennzahlen als Erfolg ausgeben.
5. Vollständiger trockener Ablauf Aufnahme→Trigger→Schnitt→Untertitel→Dashboard ohne Plattform-Upload. Entwicklungsmodus muss auch neue Recorder-/Netzwerk-Startendpunkte blockieren; Tests mit lokalen Fixtures und Mocks.
6. Ressourcen messen: CPU/RAM, Pufferverbrauch, Renderdauer und Verzögerung pro Kandidat für einen und zwei simulierte Kanäle. Vollständige bestehende Suite und CI grün. Reale Live-Abnahme separat durch Betreiber dokumentieren; synthetische Tests allein bestätigen keine robuste Livestream-Integration.

**Ergebnis:** Drei fokussierte PRs A/B/C mit Dokumentation, Tests, sichtbarer Vorschau und Grenzen. Keine eigene Modelltrainingspipeline in dieser Aufgabe. Höhere Zuschauerbindung bleibt eine anschließend zu messende Hypothese; CM-001/002 bleiben dafür relevant.
