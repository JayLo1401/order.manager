# Deployment auf dem Hetzner-Server (Ubuntu) mit Auto-Update

- Domain: `https://bestellung.jaycloud.at` (Verwaltung, Küchenmonitor und Gäste-Link `…/o/<code>`)
- Installationsordner: `/srv/bestell_manager`
- Auto-Update: Ein systemd-Timer prüft alle 5 Minuten, ob es auf GitHub neue Commits gibt, und aktualisiert dann automatisch.

Alle Befehle werden als **root** ausgeführt. Nach dem SSH-Login einmal `sudo -i` eingeben.

---

## Schritt 1 – DNS-Eintrag anlegen

In der Hetzner Console: **DNS → jaycloud.at → Record hinzufügen**

| Name       | Typ | Wert           |
|------------|-----|----------------|
| bestellung | A   | IPv4 des Servers |

Verwendet der Server auch IPv6, zusätzlich einen `AAAA`-Eintrag mit der IPv6-Adresse anlegen.

Prüfen (dauert meist 1–5 Minuten):

```sh
dig +short bestellung.jaycloud.at
```

→ muss die Server-IP ausgeben.

## Schritt 2 – Auf dem Server anmelden und Docker prüfen

```sh
ssh <dein-user>@<server-ip>
sudo -i
docker --version && docker compose version
```

Beide Befehle sollten eine Version ausgeben, weil Docker durch den service_manager schon installiert ist.

## Schritt 3 – Deploy-Key für GitHub erzeugen

Der Server braucht Lesezugriff auf das private Repo.

```sh
ssh-keygen -t ed25519 -N "" -C "hetzner-bestell-manager" -f /root/.ssh/bestell_manager_deploy
cat /root/.ssh/bestell_manager_deploy.pub
```

Die ausgegebene Zeile (beginnt mit `ssh-ed25519 …`) kopieren und dann:

1. https://github.com/JayLo1401/bestell_manager/settings/keys öffnen.
2. **Add deploy key** wählen.
3. Title: `Hetzner`, Key: die kopierte Zeile einfügen.
4. **„Allow write access“ NICHT anhaken.**
5. **Add key** klicken.

Verbindung testen:

```sh
ssh -i /root/.ssh/bestell_manager_deploy -o IdentitiesOnly=yes -T git@github.com
```

Bei der Frage `Are you sure you want to continue connecting` mit `yes` bestätigen.
Erwartete Antwort: `Hi JayLo1401/bestell_manager! You've successfully authenticated…`

## Schritt 4 – Repo klonen

Mit dem Deploy-Key klonen und den Key fest im Repo hinterlegen. Dadurch nutzen `git fetch` und der Auto-Update-Dienst später automatisch diesen Key, und er kommt dem service_manager nicht in die Quere.

```sh
cd /srv
export GIT_SSH_COMMAND="ssh -i /root/.ssh/bestell_manager_deploy -o IdentitiesOnly=yes"
git clone git@github.com:JayLo1401/bestell_manager.git /srv/bestell_manager
unset GIT_SSH_COMMAND

cd /srv/bestell_manager
git config core.sshCommand "ssh -i /root/.ssh/bestell_manager_deploy -o IdentitiesOnly=yes"
git fetch && echo "Zugriff OK"
```

## Schritt 5 – Konfiguration `.env` anlegen

Zuerst zwei Zufallswerte erzeugen und notieren:

```sh
openssl rand -hex 32     # -> für SESSION_SECRET
openssl rand -hex 16     # -> für POSTGRES_PASSWORD
```

Dann die Datei schreiben. Die Platzhalter `<…>` durch deine Werte ersetzen:

```sh
cat > /srv/bestell_manager/.env <<'EOF'
POSTGRES_USER=bestellung
POSTGRES_PASSWORD=<zweiter Zufallswert>
POSTGRES_DB=bestellung

SESSION_SECRET=<erster Zufallswert>
SESSION_COOKIE_SECURE=true
APP_BIND=127.0.0.1:8001

ADMIN_EMAIL=<deine E-Mail>
ADMIN_PASSWORD=<Start-Passwort, mind. 8 Zeichen>
ADMIN_NAME=Jürgen

ADMIN_BASE_URL=https://bestellung.jaycloud.at
GUEST_BASE_URL=https://bestellung.jaycloud.at
VAPID_SUBJECT=
EOF
chmod 600 /srv/bestell_manager/.env
```

Hinweise:
- `APP_BIND=127.0.0.1:8001` bedeutet: Die App ist nur lokal für den Reverse-Proxy erreichbar, nicht direkt aus dem Internet. Der service_manager belegt Port 8000, deshalb 8001. Prüfen, ob 8001 frei ist: `ss -ltnp | grep 8001`. Kommt keine Ausgabe, ist der Port frei.
- `ADMIN_*` wird nur beim allerersten Start verwendet. Das Passwort danach in der App ändern.
- Die `.env` ist nicht im Git und wird bei Updates nie überschrieben.
- Optional für das home_radio: `API_PASSWORD=<Zufallswert>` (und ggf. `API_USER`, `API_OWNER_EMAIL`) ergänzen. Dann liefert `GET https://bestellung.jaycloud.at/api/v1/today` mit HTTP Basic Auth den heutigen Bestelltag samt Küchen-Status und QR-Code. Ohne `API_PASSWORD` ist die API abgeschaltet.

## Schritt 6 – Erster Start

```sh
cd /srv/bestell_manager
docker compose up -d --build
docker compose logs -f app
```

Im Log erscheinen nacheinander „Fuehre Datenbank-Migrationen aus…“, „Admin … angelegt.“ und „Application startup complete“. Danach mit **Strg+C** das Log verlassen. Die App läuft weiter.

Test:

```sh
curl -s http://127.0.0.1:8001/healthz
```

→ `{"ok":true}`

## Schritt 7 – Reverse-Proxy und HTTPS

Nimm die Variante, die auch beim service_manager läuft. Welche das ist, zeigt dir:

```sh
docker ps --format '{{.Names}}' | grep -i traefik ; systemctl is-active nginx
```

### Variante A – nginx

```sh
cat > /etc/nginx/sites-available/bestell_manager <<'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name bestellung.jaycloud.at;

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
certbot --nginx -d bestellung.jaycloud.at
```

Bei certbot die Frage nach dem Redirect auf HTTPS mit „Redirect“ beantworten (bei neueren Versionen passiert das automatisch).

### Variante B – Traefik

Zuerst die Namen beim service_manager nachschauen (Netzwerk, Entrypoint, Certresolver):

```sh
docker inspect $(docker ps -q --filter "label=traefik.enable=true" | head -1) --format '{{json .Config.Labels}}' | tr ',' '\n' | grep traefik
docker network ls | grep -i traefik
```

Dann eine `docker-compose.override.yml` anlegen. Diese Datei ist nicht im Git und überlebt deshalb jedes Update. `traefik`, `websecure` und `letsencrypt` ggf. durch die Namen von oben ersetzen:

```sh
cat > /srv/bestell_manager/docker-compose.override.yml <<'EOF'
services:
  app:
    networks: [default, traefik]
    labels:
      - "traefik.enable=true"
      - "traefik.docker.network=traefik"
      - "traefik.http.routers.bestellung.rule=Host(`bestellung.jaycloud.at`)"
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

**Keine authentik-Middleware bzw. kein Forward-Auth** vor diese Domain hängen. Die Gäste müssen den Bestell-Link ohne Login öffnen können. Die App hat ihren eigenen Login.

## Schritt 8 – Testen und Passwort ändern

1. https://bestellung.jaycloud.at öffnen und mit `ADMIN_EMAIL` / `ADMIN_PASSWORD` anmelden.
2. **Einstellungen → Passwort ändern**.
3. Danach kann das Start-Passwort aus der `.env` entfernt werden:
   `sed -i 's/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=/' /srv/bestell_manager/.env`
   Das ist unkritisch, weil der Admin nur beim allerersten Start angelegt wird.
4. **Link & QR-Code → Bestell-Link für heute erstellen**, den QR-Code mit dem Handy scannen und eine Testbestellung abschicken.

## Schritt 9 – Auto-Update-Dienst einrichten

```sh
cp /srv/bestell_manager/deploy/bestell-manager-update.service /etc/systemd/system/
cp /srv/bestell_manager/deploy/bestell-manager-update.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now bestell-manager-update.timer
```

Kontrolle:

```sh
systemctl list-timers bestell-manager-update.timer
```

In der Spalte NEXT steht, wann der nächste Lauf ist. Einmal sofort ausführen und das Ergebnis ansehen:

```sh
systemctl start bestell-manager-update.service
journalctl -u bestell-manager-update.service -n 20 --no-pager
```

Gibt es keine Updates, steht dort nur „Finished …“. Das ist korrekt.

## Schritt 10 – Auto-Update testen

Am PC eine kleine Änderung committen und pushen. Spätestens 5 Minuten danach am Server:

```sh
journalctl -u bestell-manager-update.service -n 20 --no-pager
```

Erwartet wird z.B.:

```
Update c41e3bb -> 1a2b3c4
Update erfolgreich: 1a2b3c4 <Commit-Nachricht>
```

**Ab jetzt gilt: Push auf `main` = neue Version läuft nach spätestens etwa 5 Minuten.** Datenbank-Migrationen laufen beim Neustart automatisch mit.

## Schritt 11 – Tägliches Datenbank-Backup (empfohlen)

```sh
mkdir -p /srv/bestell_manager/backups
crontab -e
```

Am Ende diese Zeile einfügen. Sie macht täglich um 3:30 Uhr ein Backup und hebt es 14 Tage auf:

```cron
30 3 * * * cd /srv/bestell_manager && docker compose exec -T db pg_dump -U bestellung bestellung | gzip > backups/bestellung_$(date +\%F).sql.gz && find backups -name '*.sql.gz' -mtime +14 -delete
```

Wiederherstellen:

```sh
cd /srv/bestell_manager
gunzip -c backups/bestellung_<DATUM>.sql.gz | docker compose exec -T db psql -U bestellung bestellung
```

---

## Nützliche Befehle

```sh
cd /srv/bestell_manager
docker compose ps                                  # läuft alles?
docker compose logs -f app                         # Live-Log
tail -f data/logs/app.log                          # Logdatei der App
sh update.sh                                       # sofort manuell aktualisieren
systemctl stop bestell-manager-update.timer        # Auto-Update pausieren
systemctl start bestell-manager-update.timer       # … und wieder aktivieren
```

## Fehlersuche

| Problem | Lösung |
|---|---|
| Journal zeigt `Not possible to fast-forward` | Am Server wurde eine Datei aus dem Repo geändert. `git status` zeigt welche, `git checkout -- <datei>` verwirft die Änderung. Server-Anpassungen gehören nur in `.env` bzw. `docker-compose.override.yml`. |
| `Permission denied (publickey)` | Deploy-Key auf GitHub prüfen, `ssh -i /root/.ssh/bestell_manager_deploy -o IdentitiesOnly=yes -T git@github.com` testen. Im Repo muss `git config core.sshCommand` gesetzt sein (Schritt 4). |
| Login klappt, fliegt aber sofort wieder raus | `SESSION_COOKIE_SECURE=true` braucht HTTPS. Im nginx muss `X-Forwarded-Proto` gesetzt sein (siehe Schritt 7). |
| QR-Code zeigt falsche Adresse | `GUEST_BASE_URL` in der `.env` prüfen, dann `docker compose up -d`. |
| 502 Bad Gateway | `docker compose ps` und `docker compose logs app` prüfen. Stimmt der Port im Proxy (8001) mit `APP_BIND` überein? |
| Push-Benachrichtigungen kommen nicht | Funktionieren nur über HTTPS. Am iPhone nur, wenn die Bestellseite zum Home-Bildschirm hinzugefügt wurde. |

## Später: eigene Gäste-Domain (optional)

Soll der QR-Code z.B. auf `pizza.jaycloud.at` zeigen:

1. Einen DNS-Eintrag `pizza` anlegen.
2. Die Domain zusätzlich im Proxy eintragen (nginx: `server_name` erweitern und certbot mit `-d pizza.jaycloud.at` erneut ausführen; Traefik: `|| Host(\`pizza.jaycloud.at\`)` an die Rule anhängen).
3. In der `.env` `GUEST_BASE_URL=https://pizza.jaycloud.at` setzen.
4. `docker compose up -d` ausführen.

Auf der Gäste-Domain sind dann nur die Bestellseiten erreichbar.
