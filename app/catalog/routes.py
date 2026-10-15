from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_login, verify_csrf, verify_csrf_header
from app.catalog.defaults import add_missing_default_ingredients
from app.catalog.symbols import SYMBOL_GROUPS
from app.database import get_db
from app.events.service import today_event
from app.models.catalog import INGREDIENT_CATEGORIES, KINDS, OPTION_GROUPS, Ingredient, Product, ProductOption
from app.models.user import User
from app.templating import flash, templates

router = APIRouter(dependencies=[Depends(require_login)])


def _owned(db: Session, model, item_id: int, user: User):
    item = db.get(model, item_id)
    if item is None or item.owner_id != user.id:
        raise HTTPException(status_code=404)
    return item


def _ingredients(db: Session, user: User, kind: str = "pizza") -> list[Ingredient]:
    return list(db.scalars(
        select(Ingredient)
        .where(Ingredient.owner_id == user.id, Ingredient.kind == kind)
        .order_by(Ingredient.sort_order, Ingredient.name)
    ))


def group_by_category(ingredients: list[Ingredient]) -> list[tuple[str, str, list[Ingredient]]]:
    groups = []
    for key, label in INGREDIENT_CATEGORIES.items():
        items = [i for i in ingredients if i.category == key]
        if items:
            groups.append((key, label, items))
    return groups


def _next_sort_order(db: Session, model, user: User) -> int:
    current = db.scalar(select(func.max(model.sort_order)).where(model.owner_id == user.id))
    return (current or 0) + 10


# ---------------------------------------------------------------- Zutaten

@router.get("/ingredients")
def ingredients(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    items = _ingredients(db, user)
    event = today_event(db, user)
    return templates.TemplateResponse(request, "catalog/ingredients.html", {
        "sold_out": event.sold_out_ids if event else set(),
        "groups": group_by_category(items),
        "count": len(items),
        "active_count": sum(1 for i in items if i.active),
        "categories": INGREDIENT_CATEGORIES,
        "symbol_groups": SYMBOL_GROUPS,
    })


@router.post("/ingredients", dependencies=[Depends(verify_csrf)])
def create_ingredient(
    request: Request,
    name: str = Form(...),
    icon: str = Form(""),
    category: str = Form("other"),
    default_selected: bool = Form(False),
    vegetarian: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    name = name.strip()
    if not name:
        flash(request, "Bitte einen Namen angeben.", "error")
        return RedirectResponse("/ingredients", status_code=303)
    db.add(Ingredient(
        owner_id=user.id, kind="pizza", name=name[:80], icon=icon.strip()[:16],
        category=category if category in INGREDIENT_CATEGORIES else "other",
        default_selected=default_selected, active=True, sort_order=_next_sort_order(db, Ingredient, user),
        vegetarian=vegetarian,
    ))
    db.commit()
    flash(request, f"Zutat „{name}“ hinzugefügt.")
    return RedirectResponse("/ingredients", status_code=303)


@router.post("/ingredients/defaults", dependencies=[Depends(verify_csrf)])
def restore_default_ingredients(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    added = add_missing_default_ingredients(db, user.id)
    db.commit()
    flash(request, f"{added} Standard-Zutaten ergänzt." if added else "Alle Standard-Zutaten sind bereits vorhanden.")
    return RedirectResponse("/ingredients", status_code=303)


@router.get("/ingredients/{item_id}")
def edit_ingredient_form(
    request: Request, item_id: int, db: Session = Depends(get_db), user: User = Depends(require_login)
):
    item = _owned(db, Ingredient, item_id, user)
    return templates.TemplateResponse(request, "catalog/ingredient_edit.html", {
        "item": item, "categories": INGREDIENT_CATEGORIES, "symbol_groups": SYMBOL_GROUPS,
    })


@router.post("/ingredients/{item_id}", dependencies=[Depends(verify_csrf)])
def update_ingredient(
    request: Request,
    item_id: int,
    name: str = Form(...),
    icon: str = Form(""),
    category: str = Form("other"),
    sort_order: int = Form(0),
    active: bool = Form(False),
    default_selected: bool = Form(False),
    vegetarian: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    item = _owned(db, Ingredient, item_id, user)
    if name.strip():
        item.name = name.strip()[:80]
    item.icon = icon.strip()[:16]
    item.category = category if category in INGREDIENT_CATEGORIES else "other"
    item.sort_order = sort_order
    item.active = active
    item.default_selected = default_selected
    item.vegetarian = vegetarian
    db.commit()
    flash(request, f"Zutat „{item.name}“ gespeichert.")
    return RedirectResponse("/ingredients", status_code=303)


@router.post("/ingredients/{item_id}/toggle", dependencies=[Depends(verify_csrf)])
def toggle_ingredient(request: Request, item_id: int, db: Session = Depends(get_db), user: User = Depends(require_login)):
    item = _owned(db, Ingredient, item_id, user)
    item.active = not item.active
    db.commit()
    return RedirectResponse(f"/ingredients#ing-{item.id}", status_code=303)


@router.post("/ingredients/{item_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_ingredient(request: Request, item_id: int, db: Session = Depends(get_db), user: User = Depends(require_login)):
    item = _owned(db, Ingredient, item_id, user)
    db.delete(item)
    db.commit()
    flash(request, f"Zutat „{item.name}“ gelöscht.")
    return RedirectResponse("/ingredients", status_code=303)


# ---------------------------------------------------------------- Speisen (Vorspeisen, Pizzen, Hauptgerichte, Nachspeisen)

def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(status_code=404)
    return kind


def _dish(db: Session, kind: str, item_id: int, user: User) -> Product:
    item = _owned(db, Product, item_id, user)
    if item.kind != _kind(kind):
        raise HTTPException(status_code=404)
    return item


def _dishes(db: Session, user: User, kind: str) -> list[Product]:
    return list(db.scalars(
        select(Product).where(Product.owner_id == user.id, Product.kind == kind)
        .order_by(Product.sort_order, Product.name)
    ))


@router.get("/pizzas")
def pizzas_redirect():
    return RedirectResponse("/dishes/pizza", status_code=303)


@router.get("/dishes/{kind}")
def dishes(request: Request, kind: str, db: Session = Depends(get_db), user: User = Depends(require_login)):
    return templates.TemplateResponse(request, "catalog/dishes.html", {
        "kind": _kind(kind), "items": _dishes(db, user, kind),
    })


@router.post("/dishes/{kind}/reorder", dependencies=[Depends(verify_csrf_header)])
def reorder_dishes(
    kind: str, ids: list[int] = Body(..., embed=True), db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    """Neue Reihenfolge per Drag & Drop. Muss vor /dishes/{kind}/{item_id} stehen."""
    items = {p.id: p for p in db.scalars(
        select(Product).where(Product.owner_id == user.id, Product.kind == _kind(kind), Product.id.in_(ids or [0]))
    )}
    for index, item_id in enumerate(ids):
        if item_id in items:
            items[item_id].sort_order = (index + 1) * 10
    db.commit()
    return {"ok": True}


def _options(db: Session, user: User, kind: str) -> list[ProductOption]:
    return list(db.scalars(
        select(ProductOption)
        .where(ProductOption.owner_id == user.id, ProductOption.kind == kind)
        .order_by(ProductOption.sort_order, ProductOption.name)
    ))


def _dish_form(request: Request, db: Session, user: User, kind: str, item: Product | None):
    options = _options(db, user, kind)
    return templates.TemplateResponse(request, "catalog/dish_edit.html", {
        "kind": kind,
        "item": item,
        "groups": group_by_category(_ingredients(db, user)) if kind == "pizza" else [],
        "selected_ids": {i.id for i in item.ingredients} if item else set(),
        "symbol_groups": SYMBOL_GROUPS,
        "global_options": [o for o in options if o.all_products],
        "manual_options": [o for o in options if not o.all_products],
        "selected_option_ids": {o.id for o in item.options} if item else set(),
    })


@router.get("/dishes/{kind}/new")
def new_dish_form(request: Request, kind: str, db: Session = Depends(get_db), user: User = Depends(require_login)):
    return _dish_form(request, db, user, _kind(kind), None)


@router.get("/dishes/{kind}/{item_id}")
def edit_dish_form(
    request: Request, kind: str, item_id: int, db: Session = Depends(get_db), user: User = Depends(require_login)
):
    return _dish_form(request, db, user, kind, _dish(db, kind, item_id, user))


def _apply_dish_form(db: Session, user: User, item: Product, name, icon, description, ingredient_ids, active,
                     choice_required, option_ids):
    item.name = name.strip()[:120]
    item.icon = icon.strip()[:16]
    item.description = description.strip()
    item.active = active
    item.choice_required = choice_required
    # Zutaten gibt es nur bei Pizzen
    item.ingredients = [] if item.kind != "pizza" else list(db.scalars(
        select(Ingredient).where(Ingredient.owner_id == user.id, Ingredient.id.in_(ingredient_ids or [0]))
    ))
    # Nur Optionen mit manueller Zuordnung - "bei allen" gilt ohnehin
    item.options = list(db.scalars(
        select(ProductOption).where(
            ProductOption.owner_id == user.id,
            ProductOption.kind == item.kind,
            ProductOption.all_products.is_(False),
            ProductOption.id.in_(option_ids or [0]),
        )
    ))


@router.post("/dishes/{kind}", dependencies=[Depends(verify_csrf)])
def create_dish(
    request: Request,
    kind: str,
    name: str = Form(...),
    icon: str = Form(""),
    description: str = Form(""),
    ingredient_ids: list[int] = Form(default=[]),
    active: bool = Form(False),
    choice_required: bool = Form(False),
    option_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    kind = _kind(kind)
    if not name.strip():
        flash(request, "Bitte einen Namen angeben.", "error")
        return RedirectResponse(f"/dishes/{kind}/new", status_code=303)
    item = Product(owner_id=user.id, kind=kind, sort_order=_next_sort_order(db, Product, user))
    _apply_dish_form(db, user, item, name, icon or KINDS[kind]["icon"], description, ingredient_ids, active,
                     choice_required, option_ids)
    db.add(item)
    db.commit()
    flash(request, f"{KINDS[kind]['label']} „{item.name}“ angelegt.")
    return RedirectResponse(f"/dishes/{kind}", status_code=303)


@router.post("/dishes/{kind}/{item_id}", dependencies=[Depends(verify_csrf)])
def update_dish(
    request: Request,
    kind: str,
    item_id: int,
    name: str = Form(...),
    icon: str = Form(""),
    description: str = Form(""),
    ingredient_ids: list[int] = Form(default=[]),
    active: bool = Form(False),
    choice_required: bool = Form(False),
    option_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    item = _dish(db, kind, item_id, user)
    if not name.strip():
        name = item.name
    _apply_dish_form(db, user, item, name, icon, description, ingredient_ids, active, choice_required, option_ids)
    db.commit()
    flash(request, f"{KINDS[kind]['label']} „{item.name}“ gespeichert.")
    return RedirectResponse(f"/dishes/{kind}", status_code=303)


@router.post("/dishes/{kind}/{item_id}/toggle", dependencies=[Depends(verify_csrf)])
def toggle_dish(request: Request, kind: str, item_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_login)):
    item = _dish(db, kind, item_id, user)
    item.active = not item.active
    db.commit()
    return RedirectResponse(f"/dishes/{kind}#dish-{item.id}", status_code=303)


@router.post("/dishes/{kind}/{item_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_dish(request: Request, kind: str, item_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_login)):
    item = _dish(db, kind, item_id, user)
    db.delete(item)
    db.commit()
    flash(request, f"{KINDS[kind]['label']} „{item.name}“ gelöscht.")
    return RedirectResponse(f"/dishes/{kind}", status_code=303)


# ---------------------------------------------------------------- Optionen (Calzone, Sternpizza, Eissorte ...)

def _apply_option_form(db: Session, user: User, item: ProductOption, name, icon, description, option_group,
                       all_products, product_ids):
    item.name = name.strip()[:80]
    item.icon = icon.strip()[:16]
    item.description = description.strip()
    item.option_group = option_group if option_group in OPTION_GROUPS else "extra"
    item.all_products = all_products
    item.products = [] if all_products else list(db.scalars(
        select(Product).where(
            Product.owner_id == user.id, Product.kind == item.kind, Product.id.in_(product_ids or [0])
        )
    ))


@router.get("/options")
def options(request: Request, kind: str = "pizza", db: Session = Depends(get_db), user: User = Depends(require_login)):
    return templates.TemplateResponse(request, "catalog/options.html", {
        "kind": _kind(kind), "items": _options(db, user, kind), "groups": OPTION_GROUPS,
        "symbol_groups": SYMBOL_GROUPS,
    })


@router.post("/options/reorder", dependencies=[Depends(verify_csrf_header)])
def reorder_options(ids: list[int] = Body(..., embed=True), db: Session = Depends(get_db), user: User = Depends(require_login)):
    items = {o.id: o for o in db.scalars(
        select(ProductOption).where(ProductOption.owner_id == user.id, ProductOption.id.in_(ids or [0]))
    )}
    for index, item_id in enumerate(ids):
        if item_id in items:
            items[item_id].sort_order = (index + 1) * 10
    db.commit()
    return {"ok": True}


@router.post("/options", dependencies=[Depends(verify_csrf)])
def create_option(
    request: Request,
    kind: str = Form("pizza"),
    name: str = Form(...),
    icon: str = Form(""),
    description: str = Form(""),
    option_group: str = Form("extra"),
    all_products: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    kind = _kind(kind)
    if not name.strip():
        flash(request, "Bitte einen Namen angeben.", "error")
        return RedirectResponse(f"/options?kind={kind}", status_code=303)
    item = ProductOption(owner_id=user.id, kind=kind, active=True,
                         sort_order=_next_sort_order(db, ProductOption, user))
    _apply_option_form(db, user, item, name, icon, description, option_group, all_products, [])
    db.add(item)
    db.commit()
    if not item.all_products:
        # Direkt weiter zur Zuordnung - sonst waere die Option nirgends waehlbar
        flash(request, f"Option „{item.name}“ angelegt – jetzt den {KINDS[kind]['plural']} zuordnen.")
        return RedirectResponse(f"/options/{item.id}", status_code=303)
    flash(request, f"Option „{item.name}“ angelegt.")
    return RedirectResponse(f"/options?kind={kind}", status_code=303)


@router.get("/options/{item_id}")
def edit_option_form(request: Request, item_id: int, db: Session = Depends(get_db), user: User = Depends(require_login)):
    item = _owned(db, ProductOption, item_id, user)
    return templates.TemplateResponse(request, "catalog/option_edit.html", {
        "item": item, "kind": item.kind, "groups": OPTION_GROUPS, "symbol_groups": SYMBOL_GROUPS,
        "dishes": _dishes(db, user, item.kind), "selected_ids": {p.id for p in item.products},
    })


@router.post("/options/{item_id}", dependencies=[Depends(verify_csrf)])
def update_option(
    request: Request,
    item_id: int,
    name: str = Form(...),
    icon: str = Form(""),
    description: str = Form(""),
    option_group: str = Form("extra"),
    all_products: bool = Form(False),
    active: bool = Form(False),
    product_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    item = _owned(db, ProductOption, item_id, user)
    if not name.strip():
        name = item.name
    _apply_option_form(db, user, item, name, icon, description, option_group, all_products, product_ids)
    item.active = active
    db.commit()
    flash(request, f"Option „{item.name}“ gespeichert.")
    return RedirectResponse(f"/options?kind={item.kind}", status_code=303)


@router.post("/options/{item_id}/toggle", dependencies=[Depends(verify_csrf)])
def toggle_option(request: Request, item_id: int, db: Session = Depends(get_db), user: User = Depends(require_login)):
    item = _owned(db, ProductOption, item_id, user)
    item.active = not item.active
    db.commit()
    return RedirectResponse(f"/options?kind={item.kind}#option-{item.id}", status_code=303)


@router.post("/options/{item_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_option(request: Request, item_id: int, db: Session = Depends(get_db), user: User = Depends(require_login)):
    item = _owned(db, ProductOption, item_id, user)
    db.delete(item)
    db.commit()
    flash(request, f"Option „{item.name}“ gelöscht.")
    return RedirectResponse(f"/options?kind={item.kind}", status_code=303)
