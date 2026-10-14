import io

import segno
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import generate_token
from app.catalog.defaults import ensure_host_settings
from app.config import settings
from app.models.event import Event
from app.models.user import User
from app.timeutil import today_local


def today_event(db: Session, user: User, kind: str = "pizza") -> Event | None:
    return db.scalar(select(Event).where(
        Event.owner_id == user.id, Event.kind == kind, Event.day == today_local()
    ))


def get_or_create_today_event(db: Session, user: User, kind: str = "pizza") -> Event:
    event = today_event(db, user, kind)
    if event is None:
        host_settings = ensure_host_settings(db, user.id)
        event = Event(
            owner_id=user.id, kind=kind, day=today_local(),
            token=generate_token(24), title=host_settings.event_title, ordering_open=True,
        )
        db.add(event)
        db.flush()
    return event


def guest_url(request: Request, event: Event) -> str:
    base = settings.guest_base_url.rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base}/o/{event.token}"


def qr_svg(url: str) -> str:
    qr = segno.make(url, error="m")
    buffer = io.BytesIO()
    # omitsize: nur viewBox statt fester width/height - sonst schneidet der
    # Browser den Code ab, sobald das CSS ihn kleiner darstellt (unscanbar).
    qr.save(buffer, kind="svg", border=4, xmldecl=False, svgns=True, omitsize=True, dark="#000", light="#fff")
    return buffer.getvalue().decode()


def qr_png(url: str) -> bytes:
    qr = segno.make(url, error="m")
    buffer = io.BytesIO()
    qr.save(buffer, kind="png", scale=16, border=3)
    return buffer.getvalue()
