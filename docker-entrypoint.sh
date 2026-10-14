#!/bin/sh
set -e

echo "Warte auf Datenbank..."
python -c "
import time
import sys
from sqlalchemy import create_engine
from app.config import settings
for i in range(30):
    try:
        create_engine(settings.database_url).connect().close()
        sys.exit(0)
    except Exception as e:
        print(f'DB noch nicht bereit ({e}), warte...')
        time.sleep(1)
sys.exit(1)
"

echo "Fuehre Datenbank-Migrationen aus..."
alembic upgrade head

echo "Stelle sicher, dass ein Admin-Account existiert..."
python scripts/seed_admin.py

echo "Starte Anwendung..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
