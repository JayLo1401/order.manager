#!/bin/sh
# Auto-Update fuer den Server - wird vom systemd-Timer bestell-manager-update.timer
# regelmaessig aufgerufen. Baut nur neu, wenn es auf GitHub neue Commits gibt.
# Die DB-Migrationen laufen beim Container-Start automatisch (docker-entrypoint.sh).
set -eu

cd "$(dirname "$0")/.."
BRANCH="${BRANCH:-main}"

git fetch --quiet origin "$BRANCH"
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

echo "Update $(git rev-parse --short HEAD) -> $(git rev-parse --short "origin/$BRANCH")"
git merge --ff-only --quiet "origin/$BRANCH"
docker compose up -d --build
docker image prune -f >/dev/null

# Kurz warten und pruefen, ob die App wieder antwortet
sleep 15
if docker compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=5)"; then
    echo "Update erfolgreich: $(git log -1 --format='%h %s')"
else
    echo "WARNUNG: App antwortet nach dem Update nicht - Logs pruefen: docker compose logs app" >&2
    exit 1
fi
