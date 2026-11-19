# Arbeiten an ClipMac

Lies zuerst README.md und Aufgaben.md. Dieses Repository ist eine isolierte Entwicklungskopie; der produktive Mac ist kein Testsystem.

## Arbeitsweise

- Bearbeite genau eine freigegebene Aufgabe mit erfüllten Abhängigkeiten pro Branch und Pull Request. Branch: `task/CM-XXX-kurzer-name`.
- Erst Ist-Zustand lesen, dann kleinste zusammenhängende Änderung implementieren. Keine neuen Cloud-KI-Dienste oder kostenpflichtigen APIs.
- Tests und Vorschauen benutzen temporäre/synthetische Daten. Starte für UI-Arbeit `python -m clipmac.dev`, nicht `clipmac.launch`.
- Keine Produktionszugänge übernehmen, keine echten Uploads, Löschungen, Kontoanmeldungen oder Änderungen am laufenden Mac durchführen. Reale Konto-Abnahme übernimmt der Betreiber separat.
- Die Entwicklungs-Sperren nicht abschalten, um einen Test oder eine Vorschau zum Laufen zu bringen. Vorhandene Mock-Tests simulieren Plattformen bewusst.
- Keine Modelltrainings- oder Viralitätsbehauptungen aus gespeicherten Bewertungen ableiten. Momentvorschläge bleiben zunächst rein beratend.
- GTA-6-Profil: vier Streamer, sieben Stunden, Top fünf pro Streamer, Pakete bis fünf mit 60 Minuten Pause; Änderungen am Profil sind nicht Teil des Backlogs.
- Ein Ergebnis `pending_review` ist kein Beleg öffentlicher Sichtbarkeit. `upload_unknown` niemals automatisch erneut posten.
- Keine Geheimnisse, Browserprofile, Videos, Modelle, Logs oder echte Lerndaten committen. Fremde Lizenzhinweise erhalten. `scripts/check_publication.py` ist eine zusätzliche Prüfung, kein vollständiger Geheimnisscanner.
- Prüfe `python -m unittest discover -s tests -v`, JS-Syntax bei UI-Arbeit und `python scripts/check_publication.py`. Tests im Entwicklungs-Repo ausführen; `CLIPMAC_DEV` nicht global für die komplette Mock-Suite setzen.
- Dokumentiere Abnahmekriterien und genaue Testergebnisse im PR. Aufgabenstatus: Offen → In Arbeit → Zur Prüfung → Erledigt. Erledigt erst nach Review und Merge.
- Nicht selbstständig mergen oder auf den produktiven Mac ausrollen. Keine destruktiven Datenbankänderungen; additive Migrationen zuerst gegen Kopien synthetischer Daten testen.

## Grenzen

Die vorhandenen Render-/ML-Abhängigkeiten werden in den schnellen Tests überwiegend nicht geladen. Ein grüner Testlauf belegt weder aktuelle TikTok-DOM-Kompatibilität noch reale Uploads oder semantisch gute Schnitte. Fehlende Live-Belege ausdrücklich benennen.
