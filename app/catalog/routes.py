from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_login, verify_csrf
from app.catalog.defaults import add_missing_default_ingredients
from app.catalog.symbols import SYMBOL_GROUPS
from app.database import get_db
from app.models.catalog import INGREDIENT_CATEGORIES, Ingredient, Product
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
    return templates.TemplateResponse(request, "catalog/ingredients.html", {
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


# ---------------------------------------------------------------- Pizzen

@router.get("/pizzas")
def pizzas(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    items = db.scalars(
        select(Product).where(Product.owner_id == user.id, Product.kind == "pizza")
        .order_by(Product.sort_order, Product.name)
    ).all()
    return templates.TemplateResponse(request, "catalog/pizzas.html", {"items": items})


def _pizza_form(request: Request, db: Session, user: User, item: Product | None):
    return templates.TemplateResponse(request, "catalog/pizza_edit.html", {
        "item": item,
        "groups": group_by_category(_ingredients(db, user)),
        "selected_ids": {i.id for i in item.ingredients} if item else set(),
        "symbol_groups": SYMBOL_GROUPS,
    })


@router.get("/pizzas/new")
def new_pizza_form(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    return _pizza_form(request, db, user, None)


@router.get("/pizzas/{item_id}")
def edit_pizza_form(request: Request, item_id: int, db: Session = Depends(get_db), user: User = Depends(require_login)):
    return _pizza_form(request, db, user, _owned(db, Product, item_id, user))


def _apply_pizza_form(db: Session, user: User, item: Product, name, icon, description, ingredient_ids, active):
    item.name = name.strip()[:120]
    item.icon = icon.strip()[:16]
    item.description = description.strip()
    item.active = active
    item.ingredients = list(db.scalars(
        select(Ingredient).where(Ingredient.owner_id == user.id, Ingredient.id.in_(ingredient_ids or [0]))
    ))


@router.post("/pizzas", dependencies=[Depends(verify_csrf)])
def create_pizza(
    request: Request,
    name: str = Form(...),
    icon: str = Form("🍕"),
    description: str = Form(""),
    ingredient_ids: list[int] = Form(default=[]),
    active: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    if not name.strip():
        flash(request, "Bitte einen Namen angeben.", "error")
        return RedirectResponse("/pizzas/new", status_code=303)
    item = Product(owner_id=user.id, kind="pizza", sort_order=_next_sort_order(db, Product, user))
    _apply_pizza_form(db, user, item, name, icon, description, ingredient_ids, active)
    db.add(item)
    db.commit()
    flash(request, f"Pizza „{item.name}“ angelegt.")
    return RedirectResponse("/pizzas", status_code=303)


@router.post("/pizzas/{item_id}", dependencies=[Depends(verify_csrf)])
def update_pizza(
    request: Request,
    item_id: int,
    name: str = Form(...),
    icon: str = Form("🍕"),
    description: str = Form(""),
    ingredient_ids: list[int] = Form(default=[]),
    active: bool = Form(False),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
    user: User = Depends(require_login),
):
    item = _owned(db, Product, item_id, user)
    if not name.strip():
        name = item.name
    _apply_pizza_form(db, user, item, name, icon, description, ingredient_ids, active)
    item.sort_order = sort_order
    db.commit()
    flash(request, f"Pizza „{item.name}“ gespeichert.")
    return RedirectResponse("/pizzas", status_code=303)


@router.post("/pizzas/{item_id}/toggle", dependencies=[Depends(verify_csrf)])
def toggle_pizza(request: Request, item_id: int, db: Session = Depends(get_db), user: User = Depends(require_login)):
    item = _owned(db, Product, item_id, user)
    item.active = not item.active
    db.commit()
    return RedirectResponse(f"/pizzas#pizza-{item.id}", status_code=303)


@router.post("/pizzas/{item_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_pizza(request: Request, item_id: int, db: Session = Depends(get_db), user: User = Depends(require_login)):
    item = _owned(db, Product, item_id, user)
    db.delete(item)
    db.commit()
    flash(request, f"Pizza „{item.name}“ gelöscht.")
    return RedirectResponse("/pizzas", status_code=303)
