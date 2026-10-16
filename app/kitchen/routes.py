"""Kuechenmonitor: Live-Uebersicht der Bestellungen (Touch-optimiert)."""

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import require_login, require_login_api, verify_csrf, verify_csrf_header
from app.catalog.defaults import ensure_host_settings
from app.catalog.routes import group_by_category
from app.models.catalog import Ingredient
from app.database import get_db
from app.events.service import today_event
from app.guest.routes import end_kitchen_entry, start_kitchen_entry
from app.models.event import COURSES, Event, Guest, Order
from app.models.push import PushSubscription
from app.models.user import User
from app.orders.service import (
    OrderError,
    change_extra_orders,
    change_status,
    decline_extra_request,
    find_guest,
    order_to_dict,
    pending_extra_requests,
    set_sold_out,
)
from app.templating import flash, templates

router = APIRouter(prefix="/kitchen")


def _event_for(db: Session, user: User, event_id: int | None) -> Event | None:
    if event_id is None:
        return today_event(db, user)
    event = db.get(Event, event_id)
    if event is None or event.owner_id != user.id:
        raise HTTPException(status_code=404)
    return event


@router.get("")
def kitchen(
    request: Request,
    event_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    event = _event_for(db, user, event_id)
    return templates.TemplateResponse(request, "kitchen.html", {
        "event": event, "is_today": event_id is None,
        "identity": ensure_host_settings(db, user.id).guest_identity,
    })


@router.post("/entry", dependencies=[Depends(verify_csrf)])
def start_entry(
    request: Request,
    guest_id: str = Form(""),  # leer = "Neuer Gast"
    name: str = Form(""),
    table_no: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    """Bestellung fuer einen Gast erfassen, der direkt in der Kueche bestellt.
    Oeffnet die normale Gaeste-Bestellseite im Kuechen-Modus (ohne Bestell-Limit);
    danach geht es zurueck zum Kuechenmonitor. Entweder ein bestehender Gast
    (guest_id) oder Name/Tisch wie in den Einstellungen; gibt es den Namen
    schon, wird die Bestellung diesem Gast zugeordnet."""
    event = today_event(db, user)
    if event is None:
        return RedirectResponse("/kitchen", status_code=303)
    if event.current_course is None:
        flash(request, "Bestellungen sind geschlossen – bitte zuerst oben einen Gang freigeben.", "error")
        return RedirectResponse("/kitchen", status_code=303)
    if guest_id:
        guest = db.get(Guest, int(guest_id)) if guest_id.isdigit() else None
        if guest is None or guest.event_id != event.id:
            raise HTTPException(status_code=404)
        start_kitchen_entry(request, event, guest)
        return RedirectResponse(f"/o/{event.token}/menu", status_code=303)

    mode = ensure_host_settings(db, user.id).guest_identity
    name = " ".join(name.split())[:80] if mode in ("name", "name_and_table") else ""
    table_no = table_no.strip()[:20] if mode in ("table", "name_and_table") else ""
    if (mode in ("name", "name_and_table") and not name) or (mode in ("table", "name_and_table") and not table_no):
        missing = {"name": "einen Namen", "table": "eine Tischnummer"}.get(mode, "Name und Tischnummer")
        flash(request, f"Bitte {missing} angeben – oder einen bestehenden Gast wählen.", "error")
        return RedirectResponse("/kitchen", status_code=303)
    guest = find_guest(db, event, name, table_no)
    if guest is None:
        guest = Guest(event_id=event.id, name=name, table_no=table_no)
        db.add(guest)
        db.commit()
    start_kitchen_entry(request, event, guest)
    return RedirectResponse(f"/o/{event.token}/menu", status_code=303)


@router.get("/api/guests")
def guests_api(db: Session = Depends(get_db), user: User = Depends(require_login_api)):
    """Heutige Gaeste fuer die Auswahl beim Erfassen einer Bestellung."""
    event = today_event(db, user)
    if event is None:
        return {"guests": []}
    guests = db.scalars(select(Guest).where(Guest.event_id == event.id)).all()
    items = [{"id": g.id, "label": g.label or f"Gast {g.id}"} for g in guests]
    return {"guests": sorted(items, key=lambda g: g["label"].lower())}


@router.get("/entry/cancel")
def cancel_entry(request: Request, user: User = Depends(require_login)):
    end_kitchen_entry(request)
    return RedirectResponse("/kitchen", status_code=303)


@router.get("/api/orders")
def orders_api(event_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(require_login_api)):
    event = _event_for(db, user, event_id)
    if event is None:
        return {"event": None, "orders": []}
    orders = db.scalars(
        select(Order).where(Order.event_id == event.id)
        .options(selectinload(Order.guest))
        .order_by(Order.number)
    ).all()
    host_settings = ensure_host_settings(db, user.id)
    return {
        "event": {
            "id": event.id,
            "title": event.title,
            "ordering_open": event.ordering_open,
            "courses": event.courses,
            "current_course": event.current_course,
            # Bei unbegrenzten Bestellungen ist "Nachschlag" sinnlos
            "order_limits": {c: host_settings.order_limit(c) for c in COURSES},
            "sold_out_count": len(event.sold_out_ids),
            # Gaeste, die um Nachschlag gebeten haben
            "extra_requests": pending_extra_requests(db, event),
        },
        "orders": [order_to_dict(o) for o in orders],
    }


@router.get("/api/ingredients")
def ingredients_api(db: Session = Depends(get_db), user: User = Depends(require_login_api)):
    """Aktive Zutaten mit "heute aus"-Status, gruppiert wie in der Verwaltung."""
    event = today_event(db, user)
    if event is None:
        return {"groups": []}
    ingredients = list(db.scalars(
        select(Ingredient)
        .where(Ingredient.owner_id == user.id, Ingredient.kind == "pizza", Ingredient.active.is_(True))
        .order_by(Ingredient.sort_order, Ingredient.name)
    ))
    sold_out = event.sold_out_ids
    return {"groups": [
        {"label": label, "items": [
            {"id": i.id, "name": i.name, "icon": i.icon, "sold_out": i.id in sold_out} for i in items
        ]}
        for _, label, items in group_by_category(ingredients)
    ]}


@router.post("/api/ingredients/{ingredient_id}/sold-out", dependencies=[Depends(verify_csrf_header)])
def set_ingredient_sold_out(
    ingredient_id: int,
    sold_out: bool = Body(..., embed=True),
    db: Session = Depends(get_db),
    user: User = Depends(require_login_api),
):
    event = today_event(db, user)
    if event is None:
        raise HTTPException(status_code=409, detail="Für heute gibt es noch keinen Bestelltag.")
    ingredient = db.get(Ingredient, ingredient_id)
    if ingredient is None or ingredient.owner_id != user.id:
        raise HTTPException(status_code=404)
    set_sold_out(event, ingredient.id, sold_out)
    db.commit()
    return {"id": ingredient.id, "sold_out": sold_out, "sold_out_count": len(event.sold_out_ids)}


@router.delete("/api/guests/{guest_id}", dependencies=[Depends(verify_csrf_header)])
def delete_guest(guest_id: int, db: Session = Depends(get_db), user: User = Depends(require_login_api)):
    """Gast endgueltig loeschen (z.B. Testbestellungen). Nur wenn keine seiner
    Bestellungen mehr offen ist."""
    guest = db.get(Guest, guest_id)
    event = db.get(Event, guest.event_id) if guest else None
    if guest is None or event is None or event.owner_id != user.id:
        raise HTTPException(status_code=404)
    open_orders = db.scalar(select(func.count(Order.id)).where(
        Order.guest_id == guest.id, Order.status.in_(("new", "in_progress"))
    ))
    if open_orders:
        raise HTTPException(status_code=409, detail="Der Gast hat noch offene Bestellungen.")
    # Explizit statt nur per FK-Cascade, damit es auch ohne DB-Cascade sauber ist
    db.execute(delete(PushSubscription).where(PushSubscription.guest_id == guest.id))
    db.execute(delete(Order).where(Order.guest_id == guest.id))
    db.delete(guest)
    db.commit()
    return {"ok": True}


@router.post("/api/guests/{guest_id}/extra", dependencies=[Depends(verify_csrf_header)])
def set_guest_extra(
    guest_id: int,
    background: BackgroundTasks,
    delta: int = Body(..., embed=True),
    course: str = Body("main", embed=True),
    db: Session = Depends(get_db),
    user: User = Depends(require_login_api),
):
    """Nachschlag gilt fuer den Gang der Bestellung, auf die getippt wurde."""
    guest = db.get(Guest, guest_id)
    event = db.get(Event, guest.event_id) if guest else None
    if guest is None or event is None or event.owner_id != user.id:
        raise HTTPException(status_code=404)
    if delta not in (1, -1) or course not in COURSES:
        raise HTTPException(status_code=400)
    change_extra_orders(db, guest, event, course, delta, background)
    db.commit()
    return {"guest_id": guest.id, "course": course, "extra_orders": guest.extra_for(course)}


@router.post("/api/guests/{guest_id}/extra-request/decline", dependencies=[Depends(verify_csrf_header)])
def decline_guest_extra_request(
    guest_id: int,
    background: BackgroundTasks,
    course: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    user: User = Depends(require_login_api),
):
    """Nachschlag-Anfrage ablehnen (Erlauben laeuft ueber /extra mit delta=1)."""
    guest = db.get(Guest, guest_id)
    event = db.get(Event, guest.event_id) if guest else None
    if guest is None or event is None or event.owner_id != user.id:
        raise HTTPException(status_code=404)
    try:
        decline_extra_request(db, guest, event, course, background)
    except OrderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {"ok": True}


@router.post("/api/orders/{order_id}/status", dependencies=[Depends(verify_csrf_header)])
def set_order_status(
    order_id: int,
    background: BackgroundTasks,
    status: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    user: User = Depends(require_login_api),
):
    order = db.get(Order, order_id)
    if order is None or order.event.owner_id != user.id:
        raise HTTPException(status_code=404)
    try:
        change_status(db, order, status, background)
    except OrderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return order_to_dict(order)
