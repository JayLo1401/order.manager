"""Gaeste-Bereich: erreichbar ohne Login ueber /o/<token> (QR-Code / Link)."""

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_csrf, verify_csrf_header
from app.catalog.defaults import ensure_host_settings
from app.catalog.routes import group_by_category
from app.database import get_db
from app.models.catalog import Ingredient, Product
from app.models.event import Event, Guest, Order
from app.models.push import PushSubscription
from app.models.settings import HostSettings
from app.orders.service import (
    OrderError,
    available_today,
    can_order_more,
    change_status,
    options_for,
    order_to_dict,
    place_order,
)
from app.push.service import get_vapid_keys
from app.templating import flash, templates
from app.timeutil import today_local

router = APIRouter(prefix="/o/{token}")


class GuestContext:
    def __init__(self, event: Event, host_settings: HostSettings, guest: Guest | None):
        self.event = event
        self.settings = host_settings
        self.guest = guest

    @property
    def base(self) -> str:
        return f"/o/{self.event.token}"


def _guest_ids(request: Request) -> dict:
    return request.session.get("guests", {})


def load_context(token: str, request: Request, db: Session = Depends(get_db)) -> GuestContext:
    event = db.scalar(select(Event).where(Event.token == token))
    if event is None or event.day != today_local():
        raise HTTPException(status_code=410, detail="expired")
    guest_id = _guest_ids(request).get(str(event.id))
    guest = db.get(Guest, guest_id) if guest_id else None
    if guest is not None and guest.event_id != event.id:
        guest = None
    return GuestContext(event, ensure_host_settings(db, event.owner_id), guest)


def require_guest(ctx: GuestContext = Depends(load_context)) -> GuestContext:
    if ctx.guest is None:
        raise HTTPException(status_code=303, headers={"Location": ctx.base})
    return ctx


def _render(request: Request, template: str, ctx: GuestContext, **extra):
    return templates.TemplateResponse(request, f"guest/{template}", {"ctx": ctx, **extra})


def _my_orders(db: Session, guest: Guest) -> list[Order]:
    return list(db.scalars(select(Order).where(Order.guest_id == guest.id).order_by(Order.created_at.desc())))


@router.get("")
def entry(request: Request, ctx: GuestContext = Depends(load_context), db: Session = Depends(get_db)):
    if ctx.guest is not None:
        if _my_orders(db, ctx.guest) and not can_order_more(db, ctx.guest, ctx.settings):
            return RedirectResponse(f"{ctx.base}/status", status_code=303)
        return RedirectResponse(f"{ctx.base}/menu", status_code=303)
    return _render(request, "join.html", ctx, error=None, form={})


@router.post("/join", dependencies=[Depends(verify_csrf)])
def join(
    request: Request,
    name: str = Form(""),
    table_no: str = Form(""),
    ctx: GuestContext = Depends(load_context),
    db: Session = Depends(get_db),
):
    if ctx.guest is not None:
        return RedirectResponse(f"{ctx.base}/menu", status_code=303)
    mode = ctx.settings.guest_identity
    name = " ".join(name.split())[:80] if mode in ("name", "name_and_table") else ""
    table_no = table_no.strip()[:20] if mode in ("table", "name_and_table") else ""
    error = None
    if mode in ("name", "name_and_table") and not name:
        error = "Bitte gib deinen Namen ein."
    elif mode in ("table", "name_and_table") and not table_no:
        error = "Bitte gib deine Tischnummer ein."
    elif name and db.scalar(select(Guest.id).where(
        Guest.event_id == ctx.event.id, func.lower(Guest.name) == name.lower(), Guest.table_no == table_no
    )) is not None:
        error = "Dieser Name ist heute schon vergeben – ergänze z.B. den Anfangsbuchstaben deines Nachnamens."
    if error:
        return _render(request, "join.html", ctx, error=error, form={"name": name, "table_no": table_no})

    guest = Guest(event_id=ctx.event.id, name=name, table_no=table_no)
    db.add(guest)
    db.commit()
    guests = _guest_ids(request)
    guests[str(ctx.event.id)] = guest.id
    request.session["guests"] = guests
    return RedirectResponse(f"{ctx.base}/menu", status_code=303)


def _ordering_blocked(db: Session, ctx: GuestContext) -> RedirectResponse | None:
    if not ctx.event.ordering_open or not can_order_more(db, ctx.guest, ctx.settings):
        return RedirectResponse(f"{ctx.base}/status", status_code=303)
    return None


@router.get("/menu")
def menu(request: Request, ctx: GuestContext = Depends(require_guest), db: Session = Depends(get_db)):
    if (blocked := _ordering_blocked(db, ctx)) is not None:
        return blocked
    products = []
    if ctx.settings.allow_presets:
        products = [p for p in db.scalars(
            select(Product)
            .where(Product.owner_id == ctx.event.owner_id, Product.kind == ctx.event.kind, Product.active.is_(True))
            .order_by(Product.sort_order, Product.name)
        ) if available_today(p, ctx.event)]
    if not products and ctx.settings.allow_custom:
        return RedirectResponse(f"{ctx.base}/custom", status_code=303)
    options = options_for(db, ctx.event)
    # Welche Optionen gibt es bei welcher Pizza? (fuer das Options-Fenster)
    product_options = {p.id: [o.id for o in options if o.available_for(p)] for p in products}
    return _render(request, "menu.html", ctx, products=products, options=options,
                   product_options=product_options)


@router.get("/custom")
def custom(request: Request, ctx: GuestContext = Depends(require_guest), db: Session = Depends(get_db)):
    if (blocked := _ordering_blocked(db, ctx)) is not None:
        return blocked
    if not ctx.settings.allow_custom:
        return RedirectResponse(f"{ctx.base}/menu", status_code=303)
    ingredients = list(db.scalars(
        select(Ingredient)
        .where(Ingredient.owner_id == ctx.event.owner_id, Ingredient.kind == ctx.event.kind, Ingredient.active.is_(True))
        .order_by(Ingredient.sort_order, Ingredient.name)
    ))
    options = [o for o in options_for(db, ctx.event) if o.available_for(None)]
    return _render(request, "custom.html", ctx, groups=group_by_category(ingredients), options=options,
                   sold_out=ctx.event.sold_out_ids)


@router.post("/order", dependencies=[Depends(verify_csrf)])
def order(
    request: Request,
    product_id: int | None = Form(None),
    ingredient_ids: list[int] = Form(default=[]),
    option_ids: list[int] = Form(default=[]),
    note: str = Form(""),
    ctx: GuestContext = Depends(require_guest),
    db: Session = Depends(get_db),
):
    try:
        place_order(db, ctx.event, ctx.guest, ctx.settings, product_id, ingredient_ids, note, option_ids)
    except OrderError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(f"{ctx.base}/{'custom' if not product_id else 'menu'}", status_code=303)
    db.commit()
    return RedirectResponse(f"{ctx.base}/status?ok=1", status_code=303)


@router.get("/status")
def status_page(
    request: Request, ok: int = 0, ctx: GuestContext = Depends(require_guest), db: Session = Depends(get_db)
):
    return _render(
        request, "status.html", ctx,
        orders=_my_orders(db, ctx.guest),
        just_ordered=bool(ok),
        can_order_more=ctx.event.ordering_open and can_order_more(db, ctx.guest, ctx.settings),
        vapid_public_key=get_vapid_keys(db).vapid_public_key,
    )


@router.get("/api/status")
def status_api(ctx: GuestContext = Depends(require_guest), db: Session = Depends(get_db)):
    return {
        "ordering_open": ctx.event.ordering_open,
        "can_order_more": ctx.event.ordering_open and can_order_more(db, ctx.guest, ctx.settings),
        "orders": [order_to_dict(o) for o in _my_orders(db, ctx.guest)],
    }


@router.post("/orders/{order_id}/cancel", dependencies=[Depends(verify_csrf)])
def cancel(
    request: Request,
    order_id: int,
    ctx: GuestContext = Depends(require_guest),
    db: Session = Depends(get_db),
):
    order = db.get(Order, order_id)
    if order is None or order.guest_id != ctx.guest.id:
        raise HTTPException(status_code=404)
    if not ctx.settings.allow_cancel or order.status != "new":
        flash(request, "Diese Bestellung kann nicht mehr storniert werden – sie ist schon in Arbeit.", "error")
    else:
        change_status(db, order, "cancelled", None)
        db.commit()
        flash(request, "Bestellung storniert.")
    return RedirectResponse(f"{ctx.base}/status", status_code=303)


@router.post("/push", dependencies=[Depends(verify_csrf_header)])
def push_subscribe(
    subscription: dict = Body(...),
    ctx: GuestContext = Depends(require_guest),
    db: Session = Depends(get_db),
):
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(status_code=400, detail="Ungueltiges Abo")
    db.execute(delete(PushSubscription).where(
        PushSubscription.guest_id == ctx.guest.id, PushSubscription.endpoint == endpoint
    ))
    db.add(PushSubscription(guest_id=ctx.guest.id, endpoint=endpoint, p256dh=keys["p256dh"], auth=keys["auth"]))
    db.commit()
    return {"ok": True}


@router.get("/manifest.webmanifest")
def manifest(ctx: GuestContext = Depends(load_context)):
    # Eigenes Manifest pro Bestelltag: Wer die Seite (z.B. am iPhone fuer Push)
    # zum Home-Bildschirm hinzufuegt, landet direkt bei seiner Bestellung.
    return JSONResponse({
        "name": ctx.event.title or "Bestellung",
        "short_name": "Bestellung",
        "start_url": f"{ctx.base}/status",
        "scope": f"{ctx.base}/",
        "display": "standalone",
        "background_color": "#f5f6f8",
        "theme_color": "#1b6b3e",
        "icons": [
            {"src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }, media_type="application/manifest+json")
