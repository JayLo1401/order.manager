"""Lese-API fuer externe Anzeigen (z.B. das home_radio): Gibt es heute einen
Bestelltag? Wenn ja: Titel, Status der Kueche und QR-Code zum Bestellen.

Authentifizierung per HTTP Basic mit API_USER / API_PASSWORD aus der .env -
bewusst getrennt vom Admin-Login, damit das Geraet nur lesen kann.
"""

import base64
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.events.service import guest_url, qr_png, qr_svg, today_event
from app.models.event import Event
from app.models.user import User
from app.timeutil import today_local

router = APIRouter(prefix="/api/v1")
basic = HTTPBasic(auto_error=False)


def require_api_auth(credentials: HTTPBasicCredentials | None = Depends(basic)) -> None:
    if not settings.api_password:
        raise HTTPException(status_code=404)  # API nicht eingerichtet
    ok = credentials is not None and (
        secrets.compare_digest(credentials.username.encode(), settings.api_user.encode())
        & secrets.compare_digest(credentials.password.encode(), settings.api_password.encode())
    )
    if not ok:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": 'Basic realm="bestell-manager"'})


def course_status(event: Event) -> dict:
    """Status der Kueche fuer die Anzeige, z.B. "Vorspeisen werden angenommen"."""
    course = event.current_course
    if course is None:
        return {"code": "closed", "label": "Geschlossen", "icon": "⛔"}
    kind = event.kind_for(course)
    noun = {"starter": "Vorspeisen", "pizza": "Pizzen", "main": "Hauptspeisen", "dessert": "Nachspeisen"}[kind]
    return {"code": course, "label": f"{noun} werden angenommen", "icon": event.course_icon(course)}


@router.get("/today", dependencies=[Depends(require_api_auth)])
def today(request: Request, db: Session = Depends(get_db)):
    owner_email = (settings.api_owner_email or settings.admin_email).strip().lower()
    owner = db.scalar(select(User).where(func.lower(User.email) == owner_email))
    event = today_event(db, owner) if owner else None
    if event is None:
        return {"active": False, "date": today_local().isoformat()}
    url = guest_url(request, event)
    return {
        "active": True,
        "date": event.day.isoformat(),
        "title": event.title,
        "host_name": owner.name,
        "status": course_status(event),
        "courses": [
            {"code": c, "label": event.course_label(c), "icon": event.course_icon(c)} for c in event.courses
        ],
        "url": url,
        "qr_svg": qr_svg(url),
        "qr_png_base64": base64.b64encode(qr_png(url)).decode(),
    }
