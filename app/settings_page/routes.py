from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_login, verify_csrf
from app.catalog.defaults import ensure_host_settings
from app.database import get_db
from app.events.service import today_event
from app.models.settings import GUEST_IDENTITY_MODES
from app.models.user import User
from app.templating import flash, templates

router = APIRouter(prefix="/settings", dependencies=[Depends(require_login)])


@router.get("")
def settings_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    host_settings = ensure_host_settings(db, user.id)
    db.commit()
    return templates.TemplateResponse(request, "settings.html", {
        "s": host_settings, "identity_modes": GUEST_IDENTITY_MODES, "user": user,
    })


@router.post("", dependencies=[Depends(verify_csrf)])
def save_settings(
    request: Request,
    event_title: str = Form(""),
    welcome_text: str = Form(""),
    guest_identity: str = Form("name"),
    max_orders_per_guest: int = Form(1),
    max_custom_ingredients: int = Form(0),
    allow_presets: bool = Form(False),
    allow_custom: bool = Form(False),
    allow_note: bool = Form(False),
    allow_cancel: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    s = ensure_host_settings(db, user.id)
    s.event_title = event_title.strip()[:120] or "Pizzaabend"
    s.welcome_text = welcome_text.strip()
    s.guest_identity = guest_identity if guest_identity in GUEST_IDENTITY_MODES else "name"
    s.max_orders_per_guest = max(0, max_orders_per_guest)
    s.max_custom_ingredients = max(0, max_custom_ingredients)
    s.allow_presets = allow_presets
    s.allow_custom = allow_custom
    s.allow_note = allow_note
    s.allow_cancel = allow_cancel
    if not (allow_presets or allow_custom):
        s.allow_presets = True
        flash(request, "Mindestens eine Bestellart muss aktiv sein – vorgefertigte Pizzen wurden aktiviert.", "error")
    # Titel des heutigen Bestelltags mitziehen, damit die Aenderung sofort sichtbar ist
    event = today_event(db, user)
    if event is not None:
        event.title = s.event_title
    db.commit()
    flash(request, "Einstellungen gespeichert.")
    return RedirectResponse("/settings", status_code=303)
