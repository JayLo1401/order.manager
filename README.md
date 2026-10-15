# Bestell-Manager

Selbst gehostete Web-App für Bestellungen bei Feiern und Abenden mit Freunden: Gäste scannen einen QR-Code, bestellen am Handy und sehen live, wann ihr Essen fertig ist. Die Küche arbeitet die Bestellungen an einem Touch-Monitor ab.

Ursprünglich für **Pizzaabende** gebaut (inkl. Wunschpizza aus Zutaten), mit **Gängen** für Vorspeise, Hauptspeise und Nachspeise.

## Funktionen

### Gäste

Ohne Login, über `…/o/<token>`:

- Name und/oder Tischnummer angeben (einstellbar), bei bereits vergebenem Namen mit Rückfrage „Das bin ich“.
- Gerichte des gerade freigegebenen Gangs bestellen, Optionen wählen (z.B. Calzone, Eissorte, Schokosauce), Wunschpizza zusammenstellen, Filter „Nur vegetarisch“.
- Bei Vor- und Nachspeise auch „Ich möchte keine Vorspeise“.
- Status live verfolgen, optional Push-Benachrichtigung, wenn die Bestellung fertig ist.

### Küchenmonitor

Touch-optimiert, als Web-App installierbar:

- Kacheln nach Gang gruppiert, antippen → in Arbeit → fertig.
- Gang freigeben: Vorspeise → Geschlossen → Hauptspeise → Geschlossen → Nachspeise.
- Bestellungen für Gäste direkt erfassen, Nachschlag freigeben, Zutaten „heute aus“ markieren, Ton bei neuen Bestellungen.

### Verwaltung

- Speisen je Art (Vorspeisen, Pizzen, Hauptgerichte, Nachspeisen), Optionen, Zutaten mit Symbolbibliothek.
- Pro Tag: welche Gänge es gibt und ob die Hauptspeise Pizza oder etwas anderes ist.
- Bestell-Link/QR-Code nur am jeweiligen Tag gültig – zum Teilen per WhatsApp, als PNG oder Ausdruck.
- Mehrere Gastgeber: Registrierung mit Freischaltung durch den Haupt-Admin, jeder hat seinen eigenen Katalog.

### Lese-API

Für externe Anzeigen (z.B. ein Smart-Display in der Wohnung), siehe [API](#api).

Stack: FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Jinja2-Templates, Docker Compose.

## Lokal starten

```sh
cp .env.example .env      # ADMIN_BASE_URL / GUEST_BASE_URL lokal leer lassen
docker compose up --build
```

Dann <http://localhost:8000> öffnen und mit `ADMIN_EMAIL` / `ADMIN_PASSWORD` anmelden. Beim ersten Start legt `scripts/seed_admin.py` den Haupt-Admin inklusive Standard-Katalog an.

Tests (SQLite im Speicher):

```sh
docker compose run --rm --entrypoint sh app -c "pip install -q -r requirements-dev.txt && pytest -q"
```

Oder ohne Docker:

```sh
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```

## Ablauf

1. **Registrieren** unter `/register` → Konto ist `pending`.
2. Der Haupt-Admin schaltet unter **Benutzer** frei → der neue Gastgeber bekommt automatisch den Standard-Katalog (≈45 Zutaten, 12 klassische Pizzen, eine Vorspeise und eine Nachspeise als Beispiel).
3. **Link & QR-Code** → „Bestell-Link für heute erstellen“. Der Link gilt **nur am heutigen Tag** (Zeitzone über `TIMEZONE`, Standard Europe/Vienna). „Neuen Link erzeugen“ macht den alten ungültig, „Bestelltag löschen“ entfernt ihn samt Bestellungen (z.B. nach einem Test).
4. Unter **⚙️ Gänge** festlegen, welche Gänge es heute gibt, und im Küchenmonitor den jeweils aktiven Gang freigeben.
5. Gäste scannen, melden sich an und bestellen. Das Limit pro Gast und Gang ist einstellbar (Standard: 1, 0 = unbegrenzt).
6. **Küchenmonitor**: Kachel antippen → „Bestellung bearbeiten“ (Kachel wird orange) → erneut antippen → „Bestellung abgeschlossen“. Der Gast sieht den Status sofort am Handy.

### Küchenmonitor als App auf dem Tablet

Am Tablet in Chrome/Edge anmelden → Menü „App installieren“ (oder der Button in der Navigation). Die App startet direkt im Küchenmonitor. Der Bildschirm wird über die Wake-Lock-API wach gehalten; „Ton an“ antippen, damit bei neuen Bestellungen ein Signal ertönt (Browser erlauben Ton erst nach einer Berührung).

### Benachrichtigungen für Gäste

Web-Push funktioniert auch für Web-Apps:

- **Android / Desktop** (Chrome, Edge, Firefox): direkt im Browser nach „Benachrichtigung aktivieren“.
- **iPhone** (ab iOS 16.4): nur, wenn die Bestellseite über *Teilen → Zum Home-Bildschirm* geöffnet wird. Die Seite zeigt dafür einen Hinweis.
- Ohne Push aktualisiert sich die Statusseite automatisch und vibriert/piept, wenn die Bestellung fertig ist (solange sie offen ist).

Die VAPID-Schlüssel werden beim ersten Bedarf automatisch erzeugt und in der Datenbank gespeichert. Push funktioniert nur über HTTPS.

## API

Lese-API für externe Anzeigen. Anmeldung per **HTTP Basic Auth** mit den normalen Zugangsdaten (E-Mail + Passwort); jeder Gastgeber sieht seinen eigenen Bestelltag. Nur über HTTPS verwenden.

`GET /api/v1/today` – gibt es heute einen Bestelltag?

```json
{
  "active": true,
  "date": "2026-10-15",
  "title": "Pizzaabend",
  "host_name": "Alex",
  "status": {"code": "starter", "label": "Vorspeisen werden angenommen", "icon": "🥣"},
  "courses": [{"code": "starter", "label": "Vorspeise", "icon": "🥣"}, {"code": "main", "label": "Hauptspeise", "icon": "🍕"}],
  "url": "https://bestellung.example.com/o/<token>",
  "qr_svg": "<svg …>",
  "qr_png_base64": "iVBORw0…"
}
```

Ohne Bestelltag: `{"active": false, "date": "…"}`. `status.code` ist `closed`, `starter`, `main` oder `dessert`.

`GET /api/v1/ready?seconds=120` – Bestellungen, die in den letzten `seconds` Sekunden (10–600) fertig wurden, z.B. für eine „Bitte abholen“-Anzeige. Schlank genug für häufiges Abfragen.

```json
{
  "active": true,
  "server_time": "2026-10-15T18:00:05+00:00",
  "ready": [
    {"key": "42-1760551200", "number": 7, "guest": "Anna", "item_name": "Kürbiscremesuppe", "item_icon": "🎃",
     "options": "", "course": "starter", "course_label": "Vorspeise", "done_at": "…", "age_seconds": 4}
  ]
}
```

`key` ist pro Abschluss eindeutig – damit kann eine Anzeige jeden Eintrag genau einmal einblenden.

## Konfiguration

Alle Einstellungen kommen aus der `.env` (Vorlage: [.env.example](.env.example)). Die wichtigsten:

| Variable | Bedeutung |
| --- | --- |
| `SESSION_SECRET` | Zufallswert für die Session-Cookies (`python -c "import secrets; print(secrets.token_hex(32))"`) |
| `SESSION_COOKIE_SECURE` | `true` hinter HTTPS |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NAME` | Haupt-Admin, wird nur beim allerersten Start angelegt |
| `ADMIN_BASE_URL` | Domain für Verwaltung und Küchenmonitor, z.B. `https://bestellung.example.com` |
| `GUEST_BASE_URL` | Domain, auf die Link/QR-Code zeigen. Gleich wie `ADMIN_BASE_URL` = eine Domain für alles; eine eigene Gäste-Domain zeigt nur die Bestellseiten |
| `TIMEZONE` | Zeitzone für „heute“ (Standard `Europe/Vienna`) |
| `VAPID_SUBJECT` | Absender für Push (leer = `mailto:ADMIN_EMAIL`) |

## Deployment & Auto-Update

Schritt-für-Schritt-Anleitung für einen Linux-Server mit Docker: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**

Kurzfassung: Repo nach `/srv/order.manager` klonen, `.env` anlegen, `docker compose up -d --build`, die Domain im Reverse-Proxy auf `127.0.0.1:8001` zeigen lassen. Ein optionaler systemd-Timer prüft alle 5 Minuten auf neue Commits und aktualisiert automatisch.

## Update & Migrationen

Beim Start führt `docker-entrypoint.sh` automatisch `alembic upgrade head` aus – ein Update ist also immer nur „neuen Stand holen + neu bauen“ (automatisch per Timer oder manuell mit `sh update.sh`).

Neue Migration nach Model-Änderungen erzeugen:

```sh
docker compose run --rm -v "$PWD/migrations:/app/migrations" --entrypoint alembic app revision --autogenerate -m "beschreibung"
```

Backup der Datenbank (z.B. per Cron):

```sh
docker compose exec -T db pg_dump -U bestellung bestellung > backups/bestellung_$(date +%F).sql
```

## Versionen

Die Versionsnummer steht in [`app/__init__.py`](app/__init__.py), wird unten in der Verwaltung angezeigt und von `/healthz` geliefert. Änderungen je Version: [CHANGELOG.md](CHANGELOG.md).

Neue Version veröffentlichen: Version in `app/__init__.py` erhöhen, Abschnitt im `CHANGELOG.md` ergänzen, committen, dann

```sh
git tag v1.1.0 && git push origin main v1.1.0
gh release create v1.1.0 --title "v1.1.0" --notes-file <(sed -n '/^## \[1.1.0\]/,/^## \[/p' CHANGELOG.md | sed '$d')
```

## Projektstruktur

```text
app/
  main.py            App, Domain-Trennung Verwaltung/Gäste, Dashboard
  api/               Lese-API für externe Anzeigen (HTTP Basic Auth)
  auth/              Login, Registrierung, CSRF, Passwort
  admin/             Benutzer freischalten/verwalten (Haupt-Admin)
  catalog/           Speisen, Optionen, Zutaten, Standard-Katalog, Symbolbibliothek
  events/            Bestelltag, Gänge, Link, QR-Code (segno)
  kitchen/           Küchenmonitor + JSON-API
  guest/             Gäste-Seiten unter /o/<token>
  orders/            Bestell-Logik, Statuswechsel, Gänge
  push/              Web-Push (VAPID)
  settings_page/     Verwaltungs-Einstellungen
  models/            SQLAlchemy-Models
  templates/, static/
migrations/          Alembic
scripts/             Admin-Seed, Auto-Update
deploy/              systemd-Timer für das Auto-Update
tests/
```

## Lizenz

[PolyForm Noncommercial 1.0.0](LICENSE.md) – der Quellcode ist offen einsehbar, Nutzung und Änderung sind für private und nicht-kommerzielle Zwecke frei (auch für Vereine, Schulen und gemeinnützige Organisationen). **Kommerzielle Nutzung ist nicht erlaubt**, z.B. den Bestell-Manager als bezahlten Dienst anzubieten, zu verkaufen oder in einem Gastronomiebetrieb einzusetzen. Für eine kommerzielle Lizenz bitte über GitHub anfragen.
