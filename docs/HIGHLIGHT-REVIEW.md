# CM-012 · Bewertung und Freigabe

Die Vorschläge zeigen einen **Viral Score (experimentell)** als redaktionelle Heuristik. Seine Teilwerte sind Chat-Spitze (20 %), Teilnehmerbreite (15 %), Einstieg (20 %), Kontext (20 %) und Höhepunkt/Abschluss (25 %). Chatwerte werden pro Kanal relativ zu dessen eigener Baseline berechnet. Ein Verhältnis von 1× ergibt 0 Punkte, ab 5× sind es 100 Punkte. Die Textkriterien beruhen auf belegten Modellurteilen von 0, 1 oder 2.

Vorschläge ohne Chat stehen in einem separaten Bereich mit neu normierten Textgewichten. Fehlt ein erforderlicher Beleg, zeigt das Dashboard die belegten Einzelwerte und lässt den Gesamtwert offen. Modell, Prompt und Score-Regel sind versioniert. Die Empfehlungsschwelle ist lokal einstellbar und beginnt bei 60. Zuschauerbindung und Reichweite werden später anhand veröffentlichter Clips gemessen.

Eine gerenderte Fassung kann als **Gut**, **Mittel** oder **Schlecht** bewertet werden. Fehlermeldungen mit optionaler Sekunde sind separat. Die Bewertung und die Meldungen sind an den Hash der gerenderten Fassung gebunden.

Aufgenommene, ausreichend aktuelle Live-Kandidaten mit belegter Kategorie können nach Sichtprüfung bewusst über **In die Paketwarteschlange** freigegeben werden. Dabei gelten die bestehende Paketplanung, das Zeitfenster, Duplikat- und Überlappungsprüfungen sowie Sperren für offene Fehler. File-Hash und Regeln werden vor dem Upload erneut geprüft. Bei bekanntem Twitch-VOD mit bestätigter Zeitzuordnung vergleicht ClipMac auch mit bereits bekannten Twitch-Clips. Für Live-Kandidaten ohne bestätigte Zuordnung bleibt diese Einschränkung sichtbar. Ältere VOD- und lokale Kandidaten bleiben in der lokalen Vorschau.

Die Review- und Freigabetabellen werden additiv in der vorhandenen SQLite-Datenbank erstellt. Die freigegebene Videodatei und ihre Quellen- und Render-Hashes liegen zusätzlich in `clips/hl-…/highlight-approval.json`. Vor einem Rückwechsel auf eine ältere ClipMac-Version die Automatik pausieren und noch nicht versandte Highlight-Jobs prüfen. Die ältere Version kennt die neuen Freigabeprüfungen noch nicht.

Die optionale Vorschau `python -m clipmac.dev --data-dir .clipmac-dev/highlights --with-video` zeigt eine synthetische Highlight-Karte mit Testbild, Testton und einem absichtlich unvollständigen Beleg. Für die Wiedergabe wird lokal FFmpeg benötigt.
