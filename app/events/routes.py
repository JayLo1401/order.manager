"""Bestell-Link / QR-Code fuer den aktuellen Tag."""

from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_login, verify_csrf
from app.auth.routes import safe_next
from app.auth.security import generate_token
from app.database import get_db
from app.events.service import get_or_create_today_event, guest_url, qr_png, qr_svg, today_event
from app.models.event import Event, Guest, Order
from app.models.push import PushSubscription
from app.models.user import User
from app.orders.service import OrderError, set_courses, set_current_course
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
    share_text = f"🍽️ {event.title}: Hier kannst du bestellen: {url}" if event else ""
    return templates.TemplateResponse(request, "events/link.html", {
        "event": event,
        "order_count": len(event.orders) if event else 0,
        "url": url,
        "qr": qr_svg(url) if url else None,
        "whatsapp_url": f"https://wa.me/?text={quote(share_text)}" if event else None,
        "share_text": share_text,
        "history": history,
    })


@router.post("/create", dependencies=[Depends(verify_csrf)])
def create(
    request: Request, next: str = Form("/link"), db: Session = Depends(get_db), user: User = Depends(require_login)
):
    get_or_create_today_event(db, user)
    db.commit()
    flash(request, "Bestell-Link für heute erstellt.")
    return RedirectResponse(safe_next(next), status_code=303)


@router.post("/regenerate", dependencies=[Depends(verify_csrf)])
def regenerate(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    event = today_event(db, user)
    if event is not None:
        event.token = generate_token(24)
        db.commit()
        flash(request, "Neuer Link erzeugt. Der alte Link/QR-Code funktioniert nicht mehr.")
    return RedirectResponse("/link", status_code=303)


@router.post("/delete", dependencies=[Depends(verify_csrf)])
def delete_today(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    """Heutigen Bestelltag samt Gaesten und Bestellungen endgueltig loeschen
    (z.B. nach einem Test). Link/QR-Code sind danach ungueltig."""
    event = today_event(db, user)
    if event is not None:
        guest_ids = select(Guest.id).where(Guest.event_id == event.id)
        # Explizit statt nur per FK-Cascade, damit es auch ohne DB-Cascade sauber ist
        db.execute(delete(PushSubscription).where(PushSubscription.guest_id.in_(guest_ids)))
        db.execute(delete(Order).where(Order.event_id == event.id))
        db.execute(delete(Guest).where(Guest.event_id == event.id))
        db.delete(event)
        db.commit()
        flash(request, "Bestelltag gelöscht. Der Link/QR-Code funktioniert nicht mehr.")
    return RedirectResponse("/link", status_code=303)


@router.post("/course", dependencies=[Depends(verify_csrf)])
def switch_course(
    request: Request,
    background: BackgroundTasks,
    course: str = Form(""),
    next: str = Form("/link"),
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    """Gang zum Bestellen freigeben; leer = geschlossen."""
    event = today_event(db, user)
    if event is not None:
        try:
            set_current_course(db, event, course or None, background)
        except OrderError as exc:
            flash(request, str(exc), "error")
        else:
            db.commit()
            flash(request, f"{event.course_label(course)} freigegeben." if course else "Bestellungen geschlossen.")
    return RedirectResponse(safe_next(next), status_code=303)


@router.post("/courses", dependencies=[Depends(verify_csrf)])
def save_courses(
    request: Request,
    courses: list[str] = Form(default=[]),
    main_kind: str = Form("pizza"),
    next: str = Form("/link"),
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    event = today_event(db, user)
    if event is not None:
        try:
            set_courses(event, courses, main_kind)
        except OrderError as exc:
            flash(request, str(exc), "error")
        else:
            db.commit()
            flash(request, "Gänge für heute gespeichert.")
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
