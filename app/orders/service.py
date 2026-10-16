from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.catalog import Ingredient, Product, ProductOption
from app.models.event import COURSES, MAIN_KINDS, Event, Guest, Order
from app.models.settings import HostSettings
from app.push.service import collect_event_subscriptions, collect_subscriptions, get_vapid_keys, send_push
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
    "done": ("Deine {noun} ist fertig! {icon}", "{item} kann abgeholt werden. Guten Appetit!"),
}


# Gaenge, bei denen der Gast "keine, danke" waehlen kann
SKIPPABLE_COURSES = ("starter", "dessert")


class OrderError(Exception):
    pass


def order_to_dict(order: Order) -> dict:
    created = to_local(order.created_at)
    return {
        "id": order.id,
        "number": order.number,
        "course": order.course,
        "course_label": order.event.course_label(order.course),
        "course_icon": order.event.course_icon(order.course),
        "course_noun": order.event.course_noun(order.course),
        "status": order.status,
        "status_label": order.status_label,
        "item_name": order.item_name,
        "item_icon": order.item_icon,
        "is_custom": order.is_custom,
        "is_skip": order.is_skip,
        "vegetarian": order.vegetarian,
        "ingredients": order.ingredients or [],
        "removed_ingredients": order.removed_ingredients or [],
        "options": order.options or [],
        "note": order.note,
        "guest": order.guest.label if order.guest else "",
        "guest_id": order.guest_id,
        "guest_extra_orders": order.guest.extra_for(order.course) if order.guest else 0,
        "guest_name": order.guest.name if order.guest else "",
        "table_no": order.guest.table_no if order.guest else "",
        "created_at": created.isoformat() if created else None,
        "created_time": created.strftime("%H:%M") if created else "",
    }


def active_order_count(db: Session, guest: Guest, course: str) -> int:
    return db.scalar(select(func.count(Order.id)).where(
        Order.guest_id == guest.id, Order.course == course, Order.status != "cancelled"
    )) or 0


def find_guest(db: Session, event: Event, name: str, table_no: str) -> Guest | None:
    """Gleicher Name (ohne Gross-/Kleinschreibung) und gleicher Tisch = derselbe Gast."""
    return db.scalar(select(Guest).where(
        Guest.event_id == event.id, func.lower(Guest.name) == name.lower(), Guest.table_no == table_no
    ).order_by(Guest.id).limit(1))


def can_order_more(db: Session, guest: Guest, host_settings: HostSettings, course: str | None) -> bool:
    """Das Limit gilt pro Gang. course=None (geschlossen) -> nie."""
    if course is None:
        return False
    limit = host_settings.order_limit(course)
    return limit == 0 or active_order_count(db, guest, course) < limit + guest.extra_for(course)


def available_today(product: Product, event: Event) -> bool:
    """Aktiv, alle Zutaten aktiv und keine davon heute ausgegangen."""
    sold_out = event.sold_out_ids
    return product.available and not any(i.id in sold_out for i in product.ingredients)


def set_sold_out(event: Event, ingredient_id: int, sold_out: bool) -> None:
    ids = event.sold_out_ids
    if sold_out:
        ids.add(ingredient_id)
    else:
        ids.discard(ingredient_id)
    # Neue Liste zuweisen, damit SQLAlchemy die Aenderung an der JSON-Spalte erkennt
    event.sold_out_ingredient_ids = sorted(ids)


def options_for(db: Session, owner_id: int, kind: str) -> list[ProductOption]:
    """Alle aktiven Optionen des Gastgebers fuer eine Speisen-Art."""
    return list(db.scalars(
        select(ProductOption)
        .where(ProductOption.owner_id == owner_id, ProductOption.kind == kind, ProductOption.active.is_(True))
        .order_by(ProductOption.sort_order, ProductOption.name)
    ))


def validate_options(
    db: Session, event: Event, kind: str, product: Product | None, option_ids: list[int]
) -> list[ProductOption]:
    """product=None = Wunschpizza. Unbekannte/nicht erlaubte Optionen fuehren zu
    einem Fehler statt still ignoriert zu werden - der Gast soll bekommen, was
    er ausgewaehlt hat."""
    by_id = {o.id: o for o in options_for(db, event.owner_id, kind)}
    chosen = []
    for option_id in dict.fromkeys(option_ids):
        option = by_id.get(option_id)
        if option is None or not option.available_for(product):
            raise OrderError("Eine gewählte Option ist hier nicht verfügbar.")
        chosen.append(option)
    shapes = sum(1 for o in chosen if o.option_group == "shape")
    if shapes > 1:
        raise OrderError("Bitte wähle bei der Auswahl nur eine Möglichkeit (z.B. Calzone oder Sternpizza).")
    if product is not None and product.choice_required and not shapes:
        choices = [o.name for o in by_id.values() if o.option_group == "shape" and o.available_for(product)]
        if choices:
            raise OrderError(f"Bitte wähle bei {product.name} eine Möglichkeit: {', '.join(choices)}.")
    return sorted(chosen, key=lambda o: (o.option_group != "shape", o.sort_order, o.name))


def customize_pizza(
    db: Session, event: Event, host_settings: HostSettings, product: Product, ingredient_ids: list[int]
) -> tuple[list[Ingredient], list[Ingredient], list[Ingredient]]:
    """Fertige Pizza abgeaendert ("ohne Zwiebel, mit Jalapenos"). ingredient_ids
    ist die komplette gewuenschte Belegung. Liefert (behalten, dazu, weggelassen)."""
    wanted = set(ingredient_ids)
    base = list(product.ingredients)
    base_ids = {i.id for i in base}
    extra_ids = wanted - base_ids
    extras = list(db.scalars(
        select(Ingredient)
        .where(
            Ingredient.owner_id == event.owner_id,
            Ingredient.kind == "pizza",
            Ingredient.active.is_(True),
            Ingredient.id.in_(extra_ids or [0]),
        )
        .order_by(Ingredient.sort_order, Ingredient.name)
    ))
    if len(extras) != len(extra_ids):
        raise OrderError("Eine gewählte Zutat ist leider nicht verfügbar.")
    kept = [i for i in base if i.id in wanted]
    removed = [i for i in base if i.id not in wanted]
    if base and not kept and not extras:
        raise OrderError("Bitte lass mindestens eine Zutat auf der Pizza.")
    # Das Wunschpizza-Limit gilt auch fuers Dazunehmen - eine Pizza, die laut
    # Karte schon mehr Zutaten hat, darf aber so bleiben.
    limit = host_settings.max_custom_ingredients
    if limit and extras and len(kept) + len(extras) > max(limit, len(base)):
        raise OrderError(f"Maximal {max(limit, len(base))} Zutaten erlaubt.")
    return kept, extras, removed


def place_order(
    db: Session,
    event: Event,
    guest: Guest,
    host_settings: HostSettings,
    product_id: int | None,
    ingredient_ids: list[int],
    note: str,
    option_ids: list[int] | None = None,
    skip: bool = False,
    ignore_limit: bool = False,
    customize: bool = False,
) -> Order:
    """skip=True: "Ich moechte keine Vorspeise/Nachspeise" (nur bei diesen Gaengen).
    ignore_limit=True: Erfassung durch die Kueche, dort gilt das Bestell-Limit nicht.
    customize=True: fertige Pizza mit der Belegung aus ingredient_ids."""
    added: list[Ingredient] = []
    removed: list[Ingredient] = []
    course = event.current_course
    if course is None:
        raise OrderError("Gerade kann nichts bestellt werden.")
    if not ignore_limit and not can_order_more(db, guest, host_settings, course):
        raise OrderError("Du hast bereits die maximale Anzahl an Bestellungen erreicht.")
    kind = event.kind_for(course)

    if skip:
        if course not in SKIPPABLE_COURSES:
            raise OrderError("Die Hauptspeise kann man nicht auslassen.")
        item_name, item_icon, is_custom = f"Keine {event.course_label(course)}", "🚫", False
        product_id, ingredients, options, note = None, [], [], ""
    elif product_id:
        if kind == "pizza" and not host_settings.allow_presets:
            raise OrderError("Vorgefertigte Pizzen sind nicht verfügbar.")
        product = db.get(Product, product_id)
        if product is None or product.owner_id != event.owner_id or product.kind != kind or not product.available:
            raise OrderError("Das ist leider nicht mehr verfügbar.")
        item_name, item_icon, is_custom = product.name, product.icon, False
        ingredients = product.ingredients
        if customize and kind == "pizza":
            kept, added, removed = customize_pizza(db, event, host_settings, product, ingredient_ids)
            ingredients = kept + added
        options = validate_options(db, event, kind, product, option_ids or [])
    else:
        if kind != "pizza":
            raise OrderError("Bitte wähle etwas aus.")
        if not host_settings.allow_custom:
            raise OrderError("Wunschpizzen sind nicht verfügbar.")
        ingredients = list(db.scalars(
            select(Ingredient)
            .where(
                Ingredient.owner_id == event.owner_id,
                Ingredient.kind == "pizza",
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
        options = validate_options(db, event, kind, None, option_ids or [])

    sold_out = [i.name for i in ingredients if i.id in event.sold_out_ids]
    if sold_out:
        raise OrderError(f"Leider heute aus: {', '.join(sold_out)}. Bitte wähle etwas anderes.")

    # Event-Zeile sperren, damit parallele Bestellungen keine doppelte Nummer
    # bekommen (unter SQLite in den Tests ein No-Op).
    db.execute(select(Event.id).where(Event.id == event.id).with_for_update())
    number = (db.scalar(select(func.max(Order.number)).where(Order.event_id == event.id)) or 0) + 1

    order = Order(
        event_id=event.id,
        guest_id=guest.id,
        number=number,
        course=course,
        product_id=product_id,
        is_custom=is_custom,
        is_skip=skip,
        item_name=item_name,
        item_icon=item_icon,
        ingredients=[
            {"name": i.name, "icon": i.icon, "vegetarian": i.vegetarian, **({"added": True} if i in added else {})}
            for i in ingredients
        ],
        removed_ingredients=[{"name": i.name, "icon": i.icon} for i in removed],
        options=[{"name": o.name, "icon": o.icon, "group": o.option_group} for o in options],
        note=note.strip()[:300] if host_settings.allow_note else "",
        status="new",
    )
    db.add(order)
    db.flush()
    return order


def change_extra_orders(
    db: Session, guest: Guest, event: Event, course: str, delta: int, background: BackgroundTasks | None
) -> None:
    """Nachschlag fuer einen Gang freigeben (+1) oder zuruecknehmen (-1)."""
    extra = dict(guest.extra_by_course or {})
    extra[course] = max(0, extra.get(course, 0) + delta)
    guest.extra_by_course = extra
    db.flush()
    if background is not None and delta > 0:
        subscriptions = collect_subscriptions(db, guest.id)
        if subscriptions:
            payload = {
                "title": f"Nachschlag! {event.course_icon(course)}",
                "body": f"Es ist noch {event.course_noun(course)} übrig – du darfst noch eine bestellen.",
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

    if background is not None and new_status in PUSH_MESSAGES and not order.is_skip:
        subscriptions = collect_subscriptions(db, order.guest_id)
        if subscriptions:
            title, body = PUSH_MESSAGES[new_status]
            payload = {
                "title": title.format(noun=order.event.course_noun(order.course), icon=order.item_icon),
                "body": body.format(item=order.item_name),
                "url": f"/o/{order.event.token}/status",
                "tag": f"order-{order.id}",
            }
            background.add_task(send_push, subscriptions, get_vapid_keys(db).vapid_private_pem, payload)


def set_current_course(db: Session, event: Event, course: str | None, background: BackgroundTasks | None) -> None:
    """Gang zum Bestellen freigeben (None = geschlossen). Startet ein Gang,
    bekommen alle Gaeste mit aktivierter Benachrichtigung Bescheid."""
    if course is not None and course not in event.courses:
        raise OrderError("Diesen Gang gibt es heute nicht.")
    previous = event.current_course
    event.current_course = course
    db.flush()
    if background is not None and course is not None and course != previous:
        subscriptions = collect_event_subscriptions(db, event.id)
        if subscriptions:
            payload = {
                "title": f"{event.course_label(course)}: jetzt bestellen! {event.course_icon(course)}",
                "body": f"Du kannst jetzt deine {event.course_noun(course)} bestellen.",
                "url": f"/o/{event.token}/menu",
                "tag": f"course-{event.id}",
            }
            background.add_task(send_push, subscriptions, get_vapid_keys(db).vapid_private_pem, payload)


def set_courses(event: Event, courses: list[str], main_kind: str) -> None:
    """Welche Gaenge gibt es heute, und was gibt es als Hauptspeise?"""
    courses = [c for c in COURSES if c in courses]
    if not courses:
        raise OrderError("Mindestens ein Gang muss angeboten werden.")
    event.courses = courses
    event.main_kind = main_kind if main_kind in MAIN_KINDS else "pizza"
    if event.current_course not in courses:
        event.current_course = None
