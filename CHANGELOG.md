# Changelog

Alle nennenswerten Änderungen je Version. Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionsnummern nach [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Gäste

- Fertige Pizza vor dem Bestellen kontrollieren und abändern: Nach „Weiter“ werden die Zutaten angezeigt, einzelne lassen sich weglassen oder dazunehmen („ohne Zwiebel, + Jalapeños“). Danach folgt als eigener Schritt die Frage nach Optionen wie Calzone.
- Anmerkung bei Pizzen nur noch eingeklappt im letzten Schritt.
- Aufgeräumte Statusseite: Oben steht, was im aktuellen Gang geht („Jetzt bestellen!“, „Du kannst noch eine weitere bestellen“, „Jeder Gast darf eine Pizza bestellen“, Pause). Darunter die laufenden Bestellungen, Fertiges und Storniertes kompakt und abgetrennt unter „Erledigt“.
- Nachschlag anfragen: Ist das Limit erreicht und die Speise fertig, kann der Gast einmal um Nachschlag bitten. Erneut fragen geht erst, wenn die Küche entschieden hat.

### Küchenmonitor

- Nachschlag-Anfragen erscheinen oben als Leiste (mit Ton) und lassen sich erlauben oder ablehnen; der Gast bekommt eine Push-Nachricht.
- Abgeänderte Pizzen zeigen weggelassene und hinzugefügte Zutaten deutlich auf Kachel und im Detail.
- Schnellknöpfe „In Arbeit“ und „Fertig“ direkt auf den Kacheln – ein Tipp statt Dialog. Ein Tipp auf die Kachel zeigt weiterhin alle Details.
- Einrichtung beim ersten Öffnen eines frischen Bestelltags: Welche Gänge gibt es heute, und womit geht es los (Vorspeise, Hauptspeise, Nachspeise oder noch geschlossen)?

### Verwaltung

- Bestell-Limit pro Gast getrennt für Vorspeise, Hauptspeise und Nachspeise einstellbar (z.B. 2 Vorspeisen, 1 Hauptspeise). Das bisherige Limit wird für alle Gänge übernommen.
- Screenshots im Ordner `screenshots/`.
- Umbenannt in „Order Manager“.

## [1.0.1] – 2026-10-15

Erste veröffentlichte Version, unter der Lizenz [PolyForm Noncommercial 1.0.0](LICENSE.md) – frei für private und nicht-kommerzielle Nutzung, kommerzielle Nutzung nicht erlaubt.

### Gäste

- Bestellen per QR-Code/Link ohne Login, nur am jeweiligen Tag gültig.
- Anmeldung mit Name und/oder Tischnummer (einstellbar); vergebener Name nach Rückfrage „Ja, das bin ich“ nutzbar.
- Vorgefertigte Gerichte und Wunschpizza aus Zutaten, Optionen (z.B. Calzone, Eissorte, Schokosauce) mit Pflichtauswahl, Filter „Nur vegetarisch“.
- „Ich möchte keine Vorspeise/Nachspeise“.
- Live-Status nach Gang gruppiert, Push-Benachrichtigung (Web-Push/VAPID) bei Statuswechsel, Nachschlag und Start eines neuen Gangs.

### Küchenmonitor

- Touch-Kacheln nach Gang gruppiert, Statuswechsel neu → in Arbeit → fertig, Ton bei neuen Bestellungen, Vollbild, Wake-Lock.
- Gänge pro Tag: Vorspeise, Hauptspeise (Pizza oder andere Gerichte), Nachspeise; aktiven Gang freigeben oder Bestellungen schließen.
- Bestellungen für Gäste direkt erfassen (neuer oder bestehender Gast, ohne Bestell-Limit).
- Nachschlag pro Gast und Gang, Zutaten „heute aus“, Gast samt Bestellungen löschen.

### Verwaltung

- Speisen je Art (Vorspeisen, Pizzen, Hauptgerichte, Nachspeisen), Optionen, Zutaten mit Symbolbibliothek, Sortierung per Drag & Drop.
- Standard-Katalog für neue Gastgeber (Zutaten, 12 Pizzen, Kürbiscremesuppe, Eispalatschinke).
- Bestell-Link/QR-Code teilen (WhatsApp, PNG, Ausdruck), neu erzeugen oder den Bestelltag komplett löschen.
- Mehrere Gastgeber mit Registrierung und Freischaltung durch den Haupt-Admin.

### API

- `GET /api/v1/today`: Bestelltag, Küchen-Status und QR-Code für externe Anzeigen.
- `GET /api/v1/ready`: gerade fertige Bestellungen für eine „Bitte abholen“-Anzeige.
- Anmeldung per HTTP Basic Auth mit den normalen Zugangsdaten.

### Betrieb

- Docker Compose mit PostgreSQL, automatische Migrationen beim Start, optionales Auto-Update per systemd-Timer.
- Versionsnummer in der Fußzeile der Verwaltung und unter `/healthz`.

[1.0.1]: https://github.com/JayLo1401/order.manager/releases/tag/v1.0.1
