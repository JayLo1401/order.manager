"""Bestell-Link / QR-Code fuer den aktuellen Tag."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_login, verify_csrf
from app.auth.routes import safe_next
from app.auth.security import generate_token
from app.database import get_db
from app.events.service import get_or_create_today_event, guest_url, qr_png, qr_svg, today_event
from app.models.event import Event, Order
from app.models.user import User
from app.templating import flash, templates

router = APIRouter(prefix="/link", dependencies=[Depends(require_login)])


@router.get("")
def link_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    event = today_event(db, user)
    url = guest_url(request, event) if event else None
    history = db.execute(
        select(Event, func.count(Order.id))
        .outerjoin(Order, (Order.event_id == Event.id) & (Order.status != "cancelled"))
        .where(Event.owner_id == user.id)
        .group_by(Event.id)
        .order_by(Event.day.desc())
        .limit(30)
    ).all()
    share_text = f"🍕 {event.title}: Hier kannst du deine Pizza bestellen: {url}" if event else ""
    return templates.TemplateResponse(request, "events/link.html", {
        "event": event,
        "url": url,
        "qr": qr_svg(url) if url else None,
        "whatsapp_url": f"https://wa.me/?text={quote(share_text)}" if event else None,
        "share_text": share_text,
        "history": history,
    })


@router.post("/create", dependencies=[Depends(verify_csrf)])
def create(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    get_or_create_today_event(db, user)
    db.commit()
    flash(request, "Bestell-Link für heute erstellt.")
    return RedirectResponse("/link", status_code=303)


@router.post("/regenerate", dependencies=[Depends(verify_csrf)])
def regenerate(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    event = today_event(db, user)
    if event is not None:
        event.token = generate_token(24)
        db.commit()
        flash(request, "Neuer Link erzeugt. Der alte Link/QR-Code funktioniert nicht mehr.")
    return RedirectResponse("/link", status_code=303)


@router.post("/toggle", dependencies=[Depends(verify_csrf)])
def toggle(
    request: Request, next: str = Form("/link"), db: Session = Depends(get_db), user: User = Depends(require_login)
):
    event = today_event(db, user)
    if event is not None:
        event.ordering_open = not event.ordering_open
        db.commit()
        flash(request, "Bestellungen wieder geöffnet." if event.ordering_open else "Bestellungen pausiert.")
    return RedirectResponse(safe_next(next), status_code=303)


@router.get("/print")
def print_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    event = today_event(db, user)
    if event is None:
        return RedirectResponse("/link", status_code=303)
    url = guest_url(request, event)
    return templates.TemplateResponse(request, "events/print.html", {"event": event, "url": url, "qr": qr_svg(url)})


@router.get("/qr.png")
def qr_image(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    event = today_event(db, user)
    if event is None:
        return RedirectResponse("/link", status_code=303)
    return Response(
        qr_png(guest_url(request, event)),
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="bestellung-{event.day.isoformat()}.png"'},
    )
