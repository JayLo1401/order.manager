# Deployment auf dem Hetzner-Server (Ubuntu) mit Auto-Update

Ziel:
- `https://bestellung.jaycloud.at` → Verwaltung + Küchenmonitor
- `https://pizza.jaycloud.at` → Gäste-Seiten
- Ein **systemd-Timer** prüft alle 5 Minuten, ob es auf GitHub neue Commits gibt, und aktualisiert dann automatisch (`git pull` + Neubau; die DB-Migrationen laufen beim Start von selbst).

Alle Befehle als `root` (oder mit `sudo`) auf dem Server.

---

## 0. Voraussetzungen

Docker und das Compose-Plugin sind vom service_manager schon da. Kurz prüfen:

```sh
docker --version && docker compose version
```

Falls nicht: `curl -fsSL https://get.docker.com | sh`

## 1. DNS (Hetzner Console → DNS → jaycloud.at)

Zwei Einträge auf die Server-IP anlegen (wie bei den anderen Subdomains):

| Name        | Typ  | Wert          |
|-------------|------|---------------|
| bestellung  | A    | <Server-IPv4> |
| pizza       | A    | <Server-IPv4> |

(Falls IPv6 genutzt wird, zusätzlich je einen AAAA-Eintrag.)

## 2. Deploy-Key für das private Repo

Der Server braucht Lesezugriff auf `JayLo1401/bestell_manager`. Dafür einen eigenen, nur lesenden Schlüssel anlegen:

```sh
ssh-keygen -t ed25519 -N "" -C "hetzner-bestell-manager" -f /root/.ssh/bestell_manager_deploy
cat /root/.ssh/bestell_manager_deploy.pub
```

Den ausgegebenen Public Key auf GitHub eintragen:
**Repo → Settings → Deploy keys → Add deploy key**. Titel z.B. „Hetzner“, **„Allow write access“ NICHT anhaken**.

Damit sich der Schlüssel nicht mit dem des service_managers ins Gehege kommt, einen eigenen Host-Alias anlegen:

```sh
cat >> /root/.ssh/config <<'EOF'

Host github-bestell
    HostName github.com
    User git
    IdentityFile /root/.ssh/bestell_manager_deploy
    IdentitiesOnly yes
EOF
chmod 600 /root/.ssh/config
ssh -T github-bestell    # einmal mit "yes" bestätigen; Antwort "Hi JayLo1401/bestell_manager! ..." passt
```

## 3. Repo klonen

```sh
git clone github-bestell:JayLo1401/bestell_manager.git /opt/bestell_manager
cd /opt/bestell_manager
```

## 4. Konfiguration (`.env`)

```sh
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # -> SESSION_SECRET
nano .env
```

Folgende Werte setzen:

```ini
POSTGRES_PASSWORD=<langes zufälliges Passwort>
SESSION_SECRET=<Ausgabe von oben>
SESSION_COOKIE_SECURE=true
APP_BIND=127.0.0.1:8001

ADMIN_EMAIL=<deine E-Mail>
ADMIN_PASSWORD=<Start-Passwort, danach in der App ändern>
ADMIN_NAME=Jürgen

ADMIN_BASE_URL=https://bestellung.jaycloud.at
GUEST_BASE_URL=https://pizza.jaycloud.at
```

> `APP_BIND=127.0.0.1:8001`: Die App ist dann nur lokal für den Reverse-Proxy erreichbar. Port 8001 ist gewählt, damit es keinen Konflikt mit dem service_manager (8000) gibt – falls 8001 belegt ist, einfach einen anderen freien Port nehmen und unten im Proxy gleich eintragen.

`.env` ist nicht im Git – sie bleibt bei Updates unangetastet.

## 5. Erster Start

```sh
docker compose up -d --build
docker compose logs -f app        # warten bis "Application startup complete", dann Strg+C
curl -s http://127.0.0.1:8001/healthz   # -> {"ok":true}
```

## 6. Reverse-Proxy + HTTPS

Denselben Proxy verwenden, der auch den service_manager ausliefert. Beide Domains zeigen auf **denselben** Container – die App trennt selbst (auf `pizza.` sind nur Gäste-Seiten erreichbar).

### Variante A: nginx + certbot

```sh
cat > /etc/nginx/sites-available/bestell_manager <<'EOF'
server {
    listen 80;
    server_name bestellung.jaycloud.at pizza.jaycloud.at;

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
certbot --nginx -d bestellung.jaycloud.at -d pizza.jaycloud.at
```

### Variante B: Traefik

`APP_BIND` in der `.env` kann bleiben. Zusätzlich eine `docker-compose.override.yml` anlegen (wird von `docker compose` automatisch mitgelesen, ist nicht im Git und überlebt Updates):

```yaml
services:
  app:
    networks: [default, traefik]
    labels:
      - "traefik.enable=true"
      - "traefik.docker.network=traefik"
      - "traefik.http.routers.bestellung.rule=Host(`bestellung.jaycloud.at`) || Host(`pizza.jaycloud.at`)"
      - "traefik.http.routers.bestellung.entrypoints=websecure"
      - "traefik.http.routers.bestellung.tls.certresolver=letsencrypt"
      - "traefik.http.services.bestellung.loadbalancer.server.port=8000"

networks:
  traefik:
    external: true
```

Netzwerk-, Entrypoint- und Resolver-Namen wie beim service_manager übernehmen. Danach `docker compose up -d`.

**Wichtig bei beiden Varianten:** Die Seiten nicht hinter authentik o.ä. hängen – die Gäste müssen `pizza.jaycloud.at` ohne Login erreichen.

Test: `https://bestellung.jaycloud.at` öffnen und mit `ADMIN_EMAIL`/`ADMIN_PASSWORD` anmelden.

## 7. Auto-Update-Dienst einrichten

```sh
cp /opt/bestell_manager/deploy/bestell-manager-update.service /etc/systemd/system/
cp /opt/bestell_manager/deploy/bestell-manager-update.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now bestell-manager-update.timer
```

Kontrolle:

```sh
systemctl list-timers bestell-manager-update.timer     # nächster Lauf
systemctl start bestell-manager-update.service         # sofort einmal prüfen
journalctl -u bestell-manager-update.service -n 50     # Protokoll der Updates
```

Ab jetzt gilt: **Auf `main` pushen → spätestens nach ~5 Minuten läuft die neue Version.** Im Journal steht dann z.B.:

```
Update 1a2b3c4 -> 5d6e7f8
Update erfolgreich: 5d6e7f8 Neue Funktion XY
```

Wenn es keine neuen Commits gibt, macht der Dienst nichts (kein Neubau).

Intervall ändern: in `/etc/systemd/system/bestell-manager-update.timer` `OnUnitActiveSec=` anpassen, dann `systemctl daemon-reload`.

## 8. Backup der Datenbank (empfohlen)

```sh
mkdir -p /opt/bestell_manager/backups
crontab -e
```

Zeile hinzufügen (täglich 3:30, 14 Tage aufheben):

```cron
30 3 * * * cd /opt/bestell_manager && docker compose exec -T db pg_dump -U bestellung bestellung | gzip > backups/bestellung_$(date +\%F).sql.gz && find backups -name '*.sql.gz' -mtime +14 -delete
```

Wiederherstellen:

```sh
gunzip -c backups/bestellung_2026-10-14.sql.gz | docker compose exec -T db psql -U bestellung bestellung
```

## 9. Nützliche Befehle

```sh
cd /opt/bestell_manager
docker compose ps                      # läuft alles?
docker compose logs -f app             # Live-Log
tail -f data/logs/app.log              # App-Logdatei
sh update.sh                           # manuelles Update (ohne auf den Timer zu warten)
systemctl stop bestell-manager-update.timer    # Auto-Update pausieren
```

## Fehlersuche

| Problem | Lösung |
|---|---|
| Update-Dienst meldet `Not possible to fast-forward` | Jemand hat am Server Dateien im Repo geändert. `git status` prüfen, Änderungen mit `git checkout -- <datei>` verwerfen. Server-Anpassungen gehören in `.env` bzw. `docker-compose.override.yml`. |
| `Permission denied (publickey)` beim fetch | Deploy-Key auf GitHub prüfen, `ssh -T github-bestell` testen. |
| Login klappt nicht / fliegt sofort raus | `SESSION_COOKIE_SECURE=true` braucht HTTPS. Header `X-Forwarded-Proto` im Proxy gesetzt? |
| QR-Code zeigt falsche Domain | `GUEST_BASE_URL` in `.env` prüfen, dann `docker compose up -d`. |
| Push-Benachrichtigungen kommen nicht | Funktionieren nur über HTTPS. Am iPhone nur, wenn die Seite zum Home-Bildschirm hinzugefügt wurde. |
