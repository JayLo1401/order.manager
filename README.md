# Bestell-Manager

Web-App für Bestellungen bei Feiern – zunächst für **Pizza** (Grillen & Co. sind im Datenmodell über `kind` bereits vorgesehen).

- **Verwaltung & Küchenmonitor** (z.B. `bestellung.jaycloud.at`): Login, Registrierung mit Freischaltung durch den Haupt-Admin, Zutaten, Pizzen, Einstellungen, Bestell-Link/QR-Code, Küchenmonitor als installierbare Web-App (Tablet).
- **Gäste** (z.B. `pizza.jaycloud.at/o/<token>`): Name/Tischnummer eingeben, vorgefertigte Pizza oder Wunschpizza bestellen, Status live verfolgen, optional Push-Benachrichtigung wenn fertig.

Stack wie beim service_manager: FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Jinja2-Templates, Docker Compose.

## Lokal starten

```sh
cp .env.example .env      # ADMIN_BASE_URL / GUEST_BASE_URL lokal leer lassen
docker compose up --build
```

Dann <http://localhost:8000> öffnen und mit `ADMIN_EMAIL` / `ADMIN_PASSWORD` anmelden. Beim ersten Start legt `scripts/seed_admin.py` den Haupt-Admin inklusive Standard-Zutaten und Pizzen an.

Tests (SQLite im Speicher):

```sh
docker compose run --rm --entrypoint sh app -c "pip install -q -r requirements-dev.txt && pytest -q"
```

## Ablauf

1. **Registrieren** unter `/register` → Konto ist `pending`.
2. Der Haupt-Admin schaltet unter **Benutzer** frei → der neue Gastgeber bekommt automatisch den Standard-Katalog (≈45 Zutaten mit Symbolen, 12 klassische Pizzen).
3. **Link & QR-Code** → „Bestell-Link für heute erstellen“. Der Link gilt **nur am heutigen Tag** (Europe/Vienna). Teilen per WhatsApp, als PNG oder Ausdruck. „Neuen Link erzeugen“ macht den alten ungültig.
4. Gäste scannen, geben Name und/oder Tischnummer an (je nach Einstellung) und bestellen. Limit pro Gast ist einstellbar (Standard: 1, 0 = unbegrenzt).
5. **Küchenmonitor**: Kachel antippen → Details → „Bestellung bearbeiten“ (Kachel wird orange) → erneut antippen → „Bestellung abgeschlossen“. Der Gast sieht den Status sofort am Handy.

### Küchenmonitor als App auf dem Tablet

Am Tablet in Chrome/Edge anmelden → Menü „App installieren“ (oder der Button in der Navigation). Die App startet direkt im Küchenmonitor. Der Bildschirm wird über die Wake-Lock-API wach gehalten; „Ton an“ antippen, damit bei neuen Bestellungen ein Signal ertönt (Browser erlauben Ton erst nach einer Berührung).

### Benachrichtigungen für Gäste

Web-Push funktioniert auch für Web-Apps:

- **Android / Desktop** (Chrome, Edge, Firefox): direkt im Browser nach „Benachrichtigung aktivieren“.
- **iPhone** (ab iOS 16.4): nur, wenn die Bestellseite über *Teilen → Zum Home-Bildschirm* geöffnet wird. Die Seite zeigt dafür einen Hinweis.
- Ohne Push aktualisiert sich die Statusseite automatisch und vibriert/piept, wenn die Pizza fertig ist (solange sie offen ist).

Die VAPID-Schlüssel werden beim ersten Bedarf automatisch erzeugt und in der Datenbank gespeichert.

## Deployment auf dem Hetzner-Server & Auto-Update

Schritt-für-Schritt-Anleitung: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**

Kurzfassung: Repo nach `/opt/bestell_manager` klonen, `.env` anlegen, `docker compose up -d --build`, beide Domains im Reverse-Proxy auf `127.0.0.1:8001` zeigen lassen. Der systemd-Timer `bestell-manager-update.timer` prüft alle 5 Minuten auf neue Commits und aktualisiert automatisch.

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

## Projektstruktur

```
app/
  main.py            App, Domain-Trennung Verwaltung/Gäste, Dashboard
  auth/              Login, Registrierung, CSRF, Passwort
  admin/             Benutzer freischalten/verwalten (Haupt-Admin)
  catalog/           Zutaten, Pizzen, Standard-Katalog, Symbolbibliothek
  events/            Bestelltag, Link, QR-Code (segno)
  kitchen/           Küchenmonitor + JSON-API
  guest/             Gäste-Seiten unter /o/<token>
  orders/            Bestell-Logik, Statuswechsel
  push/              Web-Push (VAPID)
  settings_page/     Verwaltungs-Einstellungen
  models/            SQLAlchemy-Models
  templates/, static/
migrations/          Alembic
scripts/seed_admin.py
tests/
```
