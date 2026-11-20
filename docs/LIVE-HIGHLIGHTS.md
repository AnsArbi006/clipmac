# CM-012 · Live-Highlights

## Live-Aufzeichnung einrichten

1. ClipMac wie in [Installation](INSTALLATION.md) einrichten. Zusätzlich `brew install streamlink` ausführen. ClipMac benötigt `streamlink`, `ffmpeg` und `ffprobe` auf dem lokalen Suchpfad. Die Startdatei läuft auf dem Mac mit `caffeinate`.
2. Den Twitch-App-Zugang für Helix bereits in den ClipMac-Einstellungen hinterlegen. Das GTA-6-Profil bestimmt die erlaubte Spielkategorie und die vier Kanäle.
3. Über die [offizielle Twitch-Autorisierung](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/) einen Benutzer-Token für das eigene Twitch-Konto mit `chat:read` beziehen. Twitch dokumentiert Lesen und Senden als [getrennte IRC-Berechtigungen](https://dev.twitch.tv/docs/authentication/scopes/#irc-chat-scopes). Unter **Live-Highlights → Twitch-Chat verbinden** den Konto-Login und den Lese-Token eingeben. ClipMac speichert ihn lokal unter `credentials/twitch_chat.json` mit Dateimodus `0600`.
4. Bei einem Kanal **Aufnahme starten** wählen. Der aktive ClipMac-Prozess beobachtet den Stream. Der Kanalstatus zeigt Wartezeit, Aufwärmphase, Pufferauslastung und Fehler an. **Stoppen** beendet die Verarbeitung für den Kanal. Nach einem Neustart müssen die Kanäle erneut gestartet werden.

ClipMac liest den Chat über [Twitch IRC mit TLS](https://dev.twitch.tv/docs/chat/irc/). Vor dem Verbindungsaufbau und spätestens stündlich prüft ClipMac den Token mit [Twitchs Validierungsendpunkt](https://dev.twitch.tv/docs/authentication/validate-tokens/). Bei einem Verbindungsabbruch muss die Chat-Baseline erneut aufwärmen. Bei abgelaufenem oder widerrufenem Token einen neuen Lese-Token lokal speichern und den Kanal neu starten. Gespeicherte Kandidaten enthalten Chat-Zählwerte. Chatnachrichten und Benutzerkennungen dienen der flüchtigen Auswertung im Arbeitsspeicher.

## Puffer und Schnittfenster

Bis zu zwei Recorder laufen gleichzeitig. Der Ringspeicher arbeitet mit ungefähr fünfsekündigen Segmenten, deren tatsächliche Zeitgrenzen von der Quelle abhängen. Er hält etwa fünf Minuten pro Kanal und ist insgesamt auf 5 GB begrenzt. Bei knappem Datenträger pausiert die Aufnahme. Kandidaten reservieren benötigte Segmente bis zum Export. Bei fehlender Pufferabdeckung oder unklarer Kategorie erscheint ein Prüfhinweis.

Die Spike-Baseline umfasst 180 Sekunden in 10-Sekunden-Fenstern. ClipMac berücksichtigt wiederholte Nachrichten eines Teilnehmers begrenzt und wertet die Teilnehmerbreite mit aus. Der aktuelle Benutzer-Token und die Schwellen gelten ab dem nächsten Start pro Kanal. Der anfängliche Chat-Reaktionsversatz beträgt sechs Sekunden. Das Schnittfenster enthält bis zu 30 Sekunden Vor- und Nachlauf des korrigierten Triggers. Bei realen Streams sollte der Versatz mit einem bekannten Ereignis am Ziel-Mac kalibriert werden.

Bei gestoppten Aufnahmen können `live_spike` und `live_chat_delay_seconds` in der lokalen `settings.json` angepasst werden. Die Standards für `live_spike` sind `window_seconds: 10`, `baseline_seconds: 180`, `min_messages: 15`, `min_participants: 5`, `rate_multiple: 3`, `mad_multiple: 3` und `per_user_limit: 4`.

## Herkunft

Der allgemeine Aufbau aus segmentiertem Live-Puffer und Chat-Trigger wurde anhand von [stream-clipper](https://github.com/st1fo/stream-clipper/tree/70ec4edc1f27be062ad1a4822aa87b84f8d5f85e) und [twitch-clipbot](https://github.com/Higuy3000/twitch-clipbot/tree/3431055027862565bfb903185088d36047cdd00f) nachvollzogen. Die Implementierung in ClipMac ist eigenständig. Für den Transport gelten die dokumentierten Schnittstellen von [Streamlink](https://streamlink.github.io/cli.html), [FFmpeg](https://ffmpeg.org/ffmpeg-formats.html#segment_002c-stream_005fsegment_002c-ssegment) und [Twitch](https://dev.twitch.tv/docs/api/reference/).
