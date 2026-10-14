"""Kuechenmonitor: Live-Uebersicht der Bestellungen (Touch-optimiert)."""

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import require_login, require_login_api, verify_csrf_header
from app.catalog.defaults import ensure_host_settings
from app.database import get_db
from app.events.service import today_event
from app.models.event import Event, Guest, Order
from app.models.push import PushSubscription
from app.models.user import User
from app.orders.service import OrderError, change_extra_orders, change_status, order_to_dict
from app.templating import templates

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
    return templates.TemplateResponse(request, "kitchen.html", {"event": event, "is_today": event_id is None})


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
            # Bei unbegrenzten Bestellungen ist "Nachschlag" sinnlos
            "order_limit": host_settings.max_orders_per_guest,
        },
        "orders": [order_to_dict(o) for o in orders],
    }


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
    db: Session = Depends(get_db),
    user: User = Depends(require_login_api),
):
    guest = db.get(Guest, guest_id)
    event = db.get(Event, guest.event_id) if guest else None
    if guest is None or event is None or event.owner_id != user.id:
        raise HTTPException(status_code=404)
    if delta not in (1, -1):
        raise HTTPException(status_code=400)
    change_extra_orders(db, guest, event, delta, background)
    db.commit()
    return {"guest_id": guest.id, "extra_orders": guest.extra_orders}


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
