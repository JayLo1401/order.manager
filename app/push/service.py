"""Web-Push an Gaeste (z.B. "Deine Pizza ist fertig").

Funktioniert in Chrome/Edge/Firefox auf Android und Desktop direkt im Browser,
auf dem iPhone (ab iOS 16.4) nur, wenn die Seite zum Home-Bildschirm
hinzugefuegt wurde. Die VAPID-Schluessel werden beim ersten Bedarf erzeugt und
in platform_settings gespeichert.
"""

import base64
import json
import logging

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.event import Guest
from app.models.push import PushSubscription
from app.models.settings import PlatformSettings

log = logging.getLogger(__name__)


def get_vapid_keys(db: Session) -> PlatformSettings:
    platform = db.get(PlatformSettings, 1)
    if platform is None:
        platform = PlatformSettings(id=1)
        db.add(platform)
    if not platform.vapid_private_pem:
        key = ec.generate_private_key(ec.SECP256R1())
        platform.vapid_private_pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        public_raw = key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        platform.vapid_public_key = base64.urlsafe_b64encode(public_raw).rstrip(b"=").decode()
        db.commit()
    return platform


def _as_dicts(subscriptions) -> list[dict]:
    return [{"id": s.id, "endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}} for s in subscriptions]


def collect_subscriptions(db: Session, guest_id: int) -> list[dict]:
    return _as_dicts(db.scalars(select(PushSubscription).where(PushSubscription.guest_id == guest_id)))


def collect_event_subscriptions(db: Session, event_id: int) -> list[dict]:
    """Alle Gaeste eines Bestelltags, z.B. wenn der naechste Gang startet."""
    return _as_dicts(db.scalars(
        select(PushSubscription).join(Guest, Guest.id == PushSubscription.guest_id).where(Guest.event_id == event_id)
    ))


def send_push(subscriptions: list[dict], private_pem: str, payload: dict) -> None:
    """Laeuft als BackgroundTask nach der Antwort - bekommt deshalb alle Daten
    als Parameter und oeffnet nur fuer das Aufraeumen eine eigene DB-Session."""
    if not subscriptions or not private_pem:
        return
    from py_vapid import Vapid
    from pywebpush import WebPushException, webpush

    vapid = Vapid.from_pem(private_pem.encode())
    subject = settings.vapid_subject or f"mailto:{settings.admin_email}"
    expired: list[int] = []
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
                data=json.dumps(payload),
                vapid_private_key=vapid,
                vapid_claims={"sub": subject},
                ttl=3600,
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                expired.append(sub["id"])
            else:
                log.warning("Push fehlgeschlagen (%s): %s", status, exc)
        except Exception:  # noqa: BLE001 - Push darf den Ablauf nie stoeren
            log.exception("Push fehlgeschlagen")
    if expired:
        with SessionLocal() as db:
            db.execute(delete(PushSubscription).where(PushSubscription.id.in_(expired)))
            db.commit()
