# Changelog

Alle nennenswerten Änderungen je Version. Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionsnummern nach [Semantic Versioning](https://semver.org/lang/de/).

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
