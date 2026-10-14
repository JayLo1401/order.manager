#!/bin/sh
# Update auf dem Server: neuen Stand holen, Image neu bauen, Container neu starten.
# Die Datenbank-Migrationen laufen beim Start automatisch (docker-entrypoint.sh).
set -e
cd "$(dirname "$0")"

git pull --ff-only
docker compose up -d --build
docker image prune -f
docker compose logs --tail=30 app
