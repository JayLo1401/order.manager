"""Lese-API fuer externe Anzeigen (z.B. das home_radio): Gibt es heute einen
Bestelltag? Wenn ja: Titel, Status der Kueche und QR-Code zum Bestellen.

Authentifizierung per HTTP Basic mit den normalen Zugangsdaten (E-Mail +
Passwort) - jeder Gastgeber sieht so seinen eigenen Bestelltag.
"""

import base64

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.security import verify_password
from app.database import get_db
from app.events.service import guest_url, qr_png, qr_svg, today_event
from app.models.event import Event
from app.models.user import User
from app.timeutil import today_local

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
