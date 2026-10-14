"""Legt beim ersten Start den Haupt-Admin (Superuser) samt Standard-Katalog an.
Idempotent: tut nichts, sobald es irgendeinen Benutzer gibt."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.auth.security import hash_password  # noqa: E402
from app.catalog.defaults import seed_catalog  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402
from app.timeutil import now_utc  # noqa: E402


def main() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is not None:
            print("Benutzer vorhanden - nichts zu tun.")
            return
        admin = User(
            email=settings.admin_email.strip().lower(),
            name=settings.admin_name,
            password_hash=hash_password(settings.admin_password),
            role="superuser",
            status="approved",
            approved_at=now_utc(),
        )
        db.add(admin)
        db.flush()
        seed_catalog(db, admin.id)
        db.commit()
        print(f"Admin {admin.email} angelegt.")


if __name__ == "__main__":
    main()
