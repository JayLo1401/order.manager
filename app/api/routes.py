"""Lese-API fuer externe Anzeigen (z.B. ein Smart-Display): Gibt es heute einen
Bestelltag? Wenn ja: Titel, Status der Kueche und QR-Code zum Bestellen.

Authentifizierung per HTTP Basic mit den normalen Zugangsdaten (E-Mail +
Passwort) - jeder Gastgeber sieht so seinen eigenen Bestelltag.
"""

import base64
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth.security import verify_password
from app.database import get_db
from app.events.service import guest_url, qr_png, qr_svg, today_event
from app.models.event import Event, Order
from app.models.user import User
from app.timeutil import now_utc, today_local

router = APIRouter(prefix="/api/v1")
basic = HTTPBasic(auto_error=False)


def api_user(credentials: HTTPBasicCredentials | None = Depends(basic), db: Session = Depends(get_db)) -> User:
    """Wie beim Login: E-Mail + Passwort, nur freigeschaltete Benutzer."""
    user = None
    if credentials is not None:
        email = credentials.username.strip().lower()
        user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not verify_password(user.password_hash, credentials.password) or user.status != "approved":
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": 'Basic realm="bestell-manager"'})
    return user


def course_status(event: Event) -> dict:
    """Status der Kueche fuer die Anzeige, z.B. "Vorspeisen werden angenommen"."""
    course = event.current_course
    if course is None:
        return {"code": "closed", "label": "Geschlossen", "icon": "⛔"}
    kind = event.kind_for(course)
    noun = {"starter": "Vorspeisen", "pizza": "Pizzen", "main": "Hauptspeisen", "dessert": "Nachspeisen"}[kind]
    return {"code": course, "label": f"{noun} werden angenommen", "icon": event.course_icon(course)}


@router.get("/today")
def today(request: Request, db: Session = Depends(get_db), user: User = Depends(api_user)):
    event = today_event(db, user)
    if event is None:
        return {"active": False, "date": today_local().isoformat()}
    url = guest_url(request, event)
    return {
        "active": True,
        "date": event.day.isoformat(),
        "title": event.title,
        "host_name": user.name,
        "status": course_status(event),
        "courses": [
            {"code": c, "label": event.course_label(c), "icon": event.course_icon(c)} for c in event.courses
        ],
        "url": url,
        "qr_svg": qr_svg(url),
        "qr_png_base64": base64.b64encode(qr_png(url)).decode(),
    }


@router.get("/ready")
def ready(
    seconds: int = Query(120, ge=10, le=600),
    db: Session = Depends(get_db),
    user: User = Depends(api_user),
):
    """Gerade fertig gewordene Bestellungen ("Bitte abholen"), schlank genug
    fuer haeufiges Abfragen. Die Anzeige merkt sich `key` und blendet jeden
    Eintrag nur einmal ein; wird eine Bestellung wieder geoeffnet und erneut
    abgeschlossen, bekommt sie einen neuen key."""
    now = now_utc()
    event = today_event(db, user)
    items = []
    if event is not None:
        orders = db.scalars(
            select(Order)
            .where(Order.event_id == event.id, Order.status == "done", Order.is_skip.is_(False),
                   Order.done_at >= now - timedelta(seconds=seconds))
            .options(selectinload(Order.guest))
            .order_by(Order.done_at, Order.number)
        ).all()
        for o in orders:
            done_at = o.done_at if o.done_at.tzinfo else o.done_at.replace(tzinfo=timezone.utc)
            items.append({
                "key": f"{o.id}-{int(done_at.timestamp())}",
                "number": o.number,
                "guest": o.guest.label if o.guest else "",
                "item_name": o.item_name,
                "item_icon": o.item_icon,
                "options": ", ".join(x["name"] for x in o.options or []),
                "course": o.course,
                "course_label": event.course_label(o.course),
                "done_at": done_at.isoformat(),
                "age_seconds": max(0, int((now - done_at).total_seconds())),
            })
    return {"active": event is not None, "server_time": now.isoformat(), "ready": items}
