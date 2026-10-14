"""Kuechenmonitor: Live-Uebersicht der Bestellungen (Touch-optimiert)."""

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import require_login, require_login_api, verify_csrf_header
from app.database import get_db
from app.events.service import today_event
from app.models.event import Event, Order
from app.models.user import User
from app.orders.service import OrderError, change_status, order_to_dict
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
    return {
        "event": {"id": event.id, "title": event.title, "ordering_open": event.ordering_open},
        "orders": [order_to_dict(o) for o in orders],
    }


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
