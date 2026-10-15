# Deployment auf einem Linux-Server mit Docker und Auto-Update

Diese Anleitung geht von einem Ubuntu/Debian-Server mit Docker aus. Die Platzhalter ersetzt du durch deine Werte:

- Domain: `bestellung.example.com` (Verwaltung, Küchenmonitor und Gäste-Link `…/o/<code>`)
- Repo: `https://github.com/<github-user>/order.manager`
- Installationsordner: `/srv/order.manager`
- Auto-Update (optional): Ein systemd-Timer prüft alle 5 Minuten, ob es auf GitHub neue Commits gibt, und aktualisiert dann automatisch.

Alle Befehle werden als **root** ausgeführt. Nach dem SSH-Login einmal `sudo -i` eingeben.

---

## Schritt 1 – DNS-Eintrag anlegen

Beim DNS-Anbieter deiner Domain einen Eintrag anlegen:

| Name | Typ | Wert |
| --- | --- | --- |
| bestellung | A | IPv4 des Servers |

Hat der Server auch IPv6, zusätzlich einen `AAAA`-Eintrag mit der IPv6-Adresse anlegen.

Prüfen (dauert meist 1–5 Minuten):

```sh
dig +short bestellung.example.com
```

→ muss die Server-IP ausgeben.

## Schritt 2 – Auf dem Server anmelden und Docker prüfen

```sh
ssh <dein-user>@<server-ip>
sudo -i
docker --version && docker compose version
```

Beide Befehle sollten eine Version ausgeben. Falls nicht, Docker nach der [offiziellen Anleitung](https://docs.docker.com/engine/install/) installieren.

## Schritt 3 – Repo klonen

```sh
git clone https://github.com/<github-user>/order.manager.git /srv/order.manager
cd /srv/order.manager
```

**Privates Repo (z.B. eigener Fork):** Der Server braucht dann einen Lesezugriff per Deploy-Key:

```sh
ssh-keygen -t ed25519 -N "" -C "bestell-manager-deploy" -f /root/.ssh/bestell_manager_deploy
cat /root/.ssh/bestell_manager_deploy.pub
```

Die Zeile auf GitHub unter **Settings → Deploy keys → Add deploy key** eintragen („Allow write access“ **nicht** anhaken). Dann mit dem Key klonen und ihn fest im Repo hinterlegen, damit `git fetch` und das Auto-Update ihn automatisch nutzen:

```sh
export GIT_SSH_COMMAND="ssh -i /root/.ssh/bestell_manager_deploy -o IdentitiesOnly=yes"
git clone git@github.com:<github-user>/order.manager.git /srv/order.manager
unset GIT_SSH_COMMAND
cd /srv/order.manager
git config core.sshCommand "ssh -i /root/.ssh/bestell_manager_deploy -o IdentitiesOnly=yes"
git fetch && echo "Zugriff OK"
```

## Schritt 4 – Konfiguration `.env` anlegen

Zuerst zwei Zufallswerte erzeugen und notieren:

```sh
openssl rand -hex 32     # -> für SESSION_SECRET
openssl rand -hex 16     # -> für POSTGRES_PASSWORD
```

Dann die Datei schreiben. Die Platzhalter `<…>` durch deine Werte ersetzen:

```sh
cat > /srv/order.manager/.env <<'EOF'
POSTGRES_USER=bestellung
POSTGRES_PASSWORD=<zweiter Zufallswert>
POSTGRES_DB=bestellung

SESSION_SECRET=<erster Zufallswert>
SESSION_COOKIE_SECURE=true
APP_BIND=127.0.0.1:8001

ADMIN_EMAIL=<deine E-Mail>
ADMIN_PASSWORD=<Start-Passwort, mind. 8 Zeichen>
ADMIN_NAME=<dein Name>

ADMIN_BASE_URL=https://bestellung.example.com
GUEST_BASE_URL=https://bestellung.example.com
VAPID_SUBJECT=
TIMEZONE=Europe/Vienna
EOF
chmod 600 /srv/order.manager/.env
```

Hinweise:

- `APP_BIND=127.0.0.1:8001` bedeutet: Die App ist nur lokal für den Reverse-Proxy erreichbar, nicht direkt aus dem Internet. Jeder freie Port geht; prüfen mit `ss -ltnp | grep 8001` (keine Ausgabe = frei).
- `ADMIN_*` wird nur beim allerersten Start verwendet. Das Passwort danach in der App ändern.
- Die `.env` ist nicht im Git und wird bei Updates nie überschrieben.
- Für externe Anzeigen liefert `GET https://bestellung.example.com/api/v1/today` den heutigen Bestelltag samt Küchen-Status und QR-Code (siehe [README](../README.md#api)).

## Schritt 5 – Erster Start

```sh
cd /srv/order.manager
docker compose up -d --build
docker compose logs -f app
```

Im Log erscheinen nacheinander „Fuehre Datenbank-Migrationen aus…“, „Admin … angelegt.“ und „Application startup complete“. Danach mit **Strg+C** das Log verlassen. Die App läuft weiter.

Test:

```sh
curl -s http://127.0.0.1:8001/healthz
```

→ `{"ok":true,"version":"…"}`

## Schritt 6 – Reverse-Proxy und HTTPS

Läuft auf dem Server schon ein Reverse-Proxy, nimm dieselbe Variante. Welche das ist, zeigt dir:

```sh
docker ps --format '{{.Names}}' | grep -i traefik ; systemctl is-active nginx
```

### Variante A – nginx

```sh
cat > /etc/nginx/sites-available/bestell_manager <<'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name bestellung.example.com;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
EOF
ln -s /etc/nginx/sites-available/bestell_manager /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d bestellung.example.com
```

Bei certbot die Frage nach dem Redirect auf HTTPS mit „Redirect“ beantworten (bei neueren Versionen passiert das automatisch).

### Variante B – Traefik

Zuerst die Namen der bestehenden Traefik-Konfiguration nachschauen (Netzwerk, Entrypoint, Certresolver):

```sh
docker inspect $(docker ps -q --filter "label=traefik.enable=true" | head -1) --format '{{json .Config.Labels}}' | tr ',' '\n' | grep traefik
docker network ls | grep -i traefik
```

Dann eine `docker-compose.override.yml` anlegen. Diese Datei ist nicht im Git und überlebt deshalb jedes Update. `traefik`, `websecure` und `letsencrypt` ggf. durch die Namen von oben ersetzen:

```sh
cat > /srv/order.manager/docker-compose.override.yml <<'EOF'
services:
  app:
    networks: [default, traefik]
    labels:
      - "traefik.enable=true"
      - "traefik.docker.network=traefik"
      - "traefik.http.routers.bestellung.rule=Host(`bestellung.example.com`)"
      - "traefik.http.routers.bestellung.entrypoints=websecure"
      - "traefik.http.routers.bestellung.tls.certresolver=letsencrypt"
      - "traefik.http.services.bestellung.loadbalancer.server.port=8000"

networks:
  traefik:
    external: true
EOF
docker compose up -d
```

### Wichtig für beide Varianten

**Kein Forward-Auth bzw. keine Login-Middleware** (z.B. authentik) vor diese Domain hängen. Die Gäste müssen den Bestell-Link ohne Login öffnen können. Die App hat ihren eigenen Login.

## Schritt 7 – Testen und Passwort ändern

1. `https://bestellung.example.com` öffnen und mit `ADMIN_EMAIL` / `ADMIN_PASSWORD` anmelden.
2. **Einstellungen → Passwort ändern**.
3. Danach kann das Start-Passwort aus der `.env` entfernt werden:
   `sed -i 's/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=/' /srv/order.manager/.env`
   Das ist unkritisch, weil der Admin nur beim allerersten Start angelegt wird.
4. **Link & QR-Code → Bestell-Link für heute erstellen**, den QR-Code mit dem Handy scannen und eine Testbestellung abschicken. Danach kannst du den Testtag mit „Bestelltag löschen“ wieder entfernen.

## Schritt 8 – Auto-Update-Dienst einrichten (optional)

```sh
cp /srv/order.manager/deploy/order-manager-update.service /etc/systemd/system/
cp /srv/order.manager/deploy/order-manager-update.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now order-manager-update.timer
```

Liegt das Repo nicht in `/srv/order.manager`, vorher die Pfade in `order-manager-update.service` anpassen.

Kontrolle:

```sh
systemctl list-timers order-manager-update.timer
```

In der Spalte NEXT steht, wann der nächste Lauf ist. Einmal sofort ausführen und das Ergebnis ansehen:

```sh
systemctl start order-manager-update.service
journalctl -u order-manager-update.service -n 20 --no-pager
```

Gibt es keine Updates, steht dort nur „Finished …“. Das ist korrekt. Bei einem Update erscheint z.B.:

```text
Update c41e3bb -> 1a2b3c4
Update erfolgreich: 1a2b3c4 <Commit-Nachricht>
```

**Ab jetzt gilt: Neuer Stand auf `main` = neue Version läuft nach spätestens etwa 5 Minuten.** Datenbank-Migrationen laufen beim Neustart automatisch mit.

## Schritt 9 – Tägliches Datenbank-Backup (empfohlen)

```sh
mkdir -p /srv/order.manager/backups
crontab -e
```

Am Ende diese Zeile einfügen. Sie macht täglich um 3:30 Uhr ein Backup und hebt es 14 Tage auf:

```cron
30 3 * * * cd /srv/order.manager && docker compose exec -T db pg_dump -U bestellung bestellung | gzip > backups/bestellung_$(date +\%F).sql.gz && find backups -name '*.sql.gz' -mtime +14 -delete
```

Wiederherstellen:

```sh
cd /srv/order.manager
gunzip -c backups/bestellung_<DATUM>.sql.gz | docker compose exec -T db psql -U bestellung bestellung
```

---

## Nützliche Befehle

```sh
cd /srv/order.manager
docker compose ps                                  # läuft alles?
docker compose logs -f app                         # Live-Log
tail -f data/logs/app.log                          # Logdatei der App
sh update.sh                                       # sofort manuell aktualisieren
systemctl stop order-manager-update.timer         # Auto-Update pausieren
systemctl start order-manager-update.timer        # … und wieder aktivieren
```

## Fehlersuche

| Problem | Lösung |
| --- | --- |
| Journal zeigt `Not possible to fast-forward` | Am Server wurde eine Datei aus dem Repo geändert. `git status` zeigt welche, `git checkout -- <datei>` verwirft die Änderung. Server-Anpassungen gehören nur in `.env` bzw. `docker-compose.override.yml`. |
| `Permission denied (publickey)` (privates Repo) | Deploy-Key auf GitHub prüfen, `ssh -i /root/.ssh/bestell_manager_deploy -o IdentitiesOnly=yes -T git@github.com` testen. Im Repo muss `git config core.sshCommand` gesetzt sein (Schritt 3). |
| Login klappt, fliegt aber sofort wieder raus | `SESSION_COOKIE_SECURE=true` braucht HTTPS. Im nginx muss `X-Forwarded-Proto` gesetzt sein (siehe Schritt 6). |
| QR-Code zeigt falsche Adresse | `GUEST_BASE_URL` in der `.env` prüfen, dann `docker compose up -d`. |
| 502 Bad Gateway | `docker compose ps` und `docker compose logs app` prüfen. Stimmt der Port im Proxy (8001) mit `APP_BIND` überein? |
| Push-Benachrichtigungen kommen nicht | Funktionieren nur über HTTPS. Am iPhone nur, wenn die Bestellseite zum Home-Bildschirm hinzugefügt wurde. |

## Optional: eigene Gäste-Domain

Soll der QR-Code z.B. auf `pizza.example.com` zeigen:

1. Einen DNS-Eintrag `pizza` anlegen.
2. Die Domain zusätzlich im Proxy eintragen (nginx: `server_name` erweitern und certbot mit `-d pizza.example.com` erneut ausführen; Traefik: ``|| Host(`pizza.example.com`)`` an die Rule anhängen).
3. In der `.env` `GUEST_BASE_URL=https://pizza.example.com` setzen.
4. `docker compose up -d` ausführen.

Auf der Gäste-Domain sind dann nur die Bestellseiten erreichbar.
