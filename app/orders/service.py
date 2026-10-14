from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.catalog import Ingredient, Product
from app.models.event import Event, Guest, Order
from app.models.settings import HostSettings
from app.push.service import collect_subscriptions, get_vapid_keys, send_push
from app.timeutil import now_utc, to_local

# Erlaubte Statuswechsel in der Kueche. "new" zurueck ist erlaubt, falls man
# sich vertippt hat.
KITCHEN_TRANSITIONS = {
    "new": {"in_progress", "done", "cancelled"},
    "in_progress": {"new", "done", "cancelled"},
    "done": {"in_progress"},
    "cancelled": {"new"},
}

PUSH_MESSAGES = {
    "in_progress": ("Deine Bestellung ist in Arbeit 👨‍🍳", "{item} wird gerade zubereitet."),
    "done": ("Deine Pizza ist fertig! 🍕", "{item} kann abgeholt werden. Guten Appetit!"),
}


class OrderError(Exception):
    pass


def order_to_dict(order: Order) -> dict:
    created = to_local(order.created_at)
    return {
        "id": order.id,
        "number": order.number,
        "status": order.status,
        "status_label": order.status_label,
        "item_name": order.item_name,
        "item_icon": order.item_icon,
        "is_custom": order.is_custom,
        "vegetarian": order.vegetarian,
        "ingredients": order.ingredients or [],
        "note": order.note,
        "guest": order.guest.label if order.guest else "",
        "guest_id": order.guest_id,
        "guest_extra_orders": order.guest.extra_orders if order.guest else 0,
        "guest_name": order.guest.name if order.guest else "",
        "table_no": order.guest.table_no if order.guest else "",
        "created_at": created.isoformat() if created else None,
        "created_time": created.strftime("%H:%M") if created else "",
    }


def active_order_count(db: Session, guest: Guest) -> int:
    return db.scalar(
        select(func.count(Order.id)).where(Order.guest_id == guest.id, Order.status != "cancelled")
    ) or 0


def can_order_more(db: Session, guest: Guest, host_settings: HostSettings) -> bool:
    limit = host_settings.max_orders_per_guest
    return limit == 0 or active_order_count(db, guest) < limit + guest.extra_orders


def place_order(
    db: Session,
    event: Event,
    guest: Guest,
    host_settings: HostSettings,
    product_id: int | None,
    ingredient_ids: list[int],
    note: str,
) -> Order:
    if not event.ordering_open:
        raise OrderError("Bestellungen sind gerade pausiert.")
    if not can_order_more(db, guest, host_settings):
        raise OrderError("Du hast bereits die maximale Anzahl an Bestellungen erreicht.")

    if product_id:
        if not host_settings.allow_presets:
            raise OrderError("Vorgefertigte Pizzen sind nicht verfügbar.")
        product = db.get(Product, product_id)
        if product is None or product.owner_id != event.owner_id or not product.available:
            raise OrderError("Diese Pizza ist leider nicht mehr verfügbar.")
        item_name, item_icon, is_custom = product.name, product.icon, False
        ingredients = product.ingredients
    else:
        if not host_settings.allow_custom:
            raise OrderError("Wunschpizzen sind nicht verfügbar.")
        ingredients = list(db.scalars(
            select(Ingredient)
            .where(
                Ingredient.owner_id == event.owner_id,
                Ingredient.kind == event.kind,
                Ingredient.active.is_(True),
                Ingredient.id.in_(ingredient_ids or [0]),
            )
            .order_by(Ingredient.sort_order, Ingredient.name)
        ))
        if not ingredients:
            raise OrderError("Bitte wähle mindestens eine Zutat.")
        if host_settings.max_custom_ingredients and len(ingredients) > host_settings.max_custom_ingredients:
            raise OrderError(f"Maximal {host_settings.max_custom_ingredients} Zutaten erlaubt.")
        item_name, item_icon, is_custom = "Wunschpizza", "✨", True
        product_id = None

    # Event-Zeile sperren, damit parallele Bestellungen keine doppelte Nummer
    # bekommen (unter SQLite in den Tests ein No-Op).
    db.execute(select(Event.id).where(Event.id == event.id).with_for_update())
    number = (db.scalar(select(func.max(Order.number)).where(Order.event_id == event.id)) or 0) + 1

    order = Order(
        event_id=event.id,
        guest_id=guest.id,
        number=number,
        product_id=product_id,
        is_custom=is_custom,
        item_name=item_name,
        item_icon=item_icon,
        ingredients=[{"name": i.name, "icon": i.icon, "vegetarian": i.vegetarian} for i in ingredients],
        note=note.strip()[:300] if host_settings.allow_note else "",
        status="new",
    )
    db.add(order)
    db.flush()
    return order


def change_extra_orders(db: Session, guest: Guest, event: Event, delta: int, background: BackgroundTasks | None) -> None:
    """Nachschlag freigeben (+1) oder zuruecknehmen (-1)."""
    guest.extra_orders = max(0, guest.extra_orders + delta)
    db.flush()
    if background is not None and delta > 0:
        subscriptions = collect_subscriptions(db, guest.id)
        if subscriptions:
            payload = {
                "title": "Nachschlag! 🍕",
                "body": "Es ist noch Pizza übrig – du darfst noch eine bestellen.",
                "url": f"/o/{event.token}/menu",
                "tag": f"extra-{guest.id}",
            }
            background.add_task(send_push, subscriptions, get_vapid_keys(db).vapid_private_pem, payload)


def change_status(db: Session, order: Order, new_status: str, background: BackgroundTasks | None) -> None:
    if new_status not in KITCHEN_TRANSITIONS.get(order.status, set()):
        raise OrderError("Dieser Statuswechsel ist nicht möglich.")
    order.status = new_status
    if new_status == "in_progress":
        order.started_at = order.started_at or now_utc()
        order.done_at = None
    elif new_status == "done":
        order.done_at = now_utc()
    elif new_status == "new":
        order.started_at = None
        order.done_at = None
    db.flush()

    if background is not None and new_status in PUSH_MESSAGES:
        subscriptions = collect_subscriptions(db, order.guest_id)
        if subscriptions:
            title, body = PUSH_MESSAGES[new_status]
            payload = {
                "title": title,
                "body": body.format(item=order.item_name),
                "url": f"/o/{order.event.token}/status",
                "tag": f"order-{order.id}",
            }
            background.add_task(send_push, subscriptions, get_vapid_keys(db).vapid_private_pem, payload)
