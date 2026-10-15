from sqlalchemy import select

from app.auth.security import hash_password
from app.catalog.defaults import seed_catalog
from app.models.catalog import Ingredient, Product
from app.models.user import User
from tests.conftest import csrf_from, login


def _pizza_ids(db_session, owner_id):
    return [p.id for p in db_session.scalars(
        select(Product).where(Product.owner_id == owner_id, Product.kind == "pizza").order_by(Product.sort_order)
    )]


def _pizza(db_session, owner_id, name):
    return db_session.scalar(select(Product).where(Product.owner_id == owner_id, Product.name == name))


def test_vegetarian_derived_from_ingredients(client, db_session, admin):
    margherita = _pizza(db_session, admin.id, "Margherita")
    salami = _pizza(db_session, admin.id, "Salami")
    assert margherita.vegetarian is True
    assert salami.vegetarian is False

    # Basilikum als "nicht vegetarisch" markieren -> Margherita kippt automatisch
    login(client, "admin@test.at", "geheim123")
    basil = next(i for i in margherita.ingredients if i.name == "Basilikum")
    token = csrf_from(client, f"/ingredients/{basil.id}")
    client.post(f"/ingredients/{basil.id}", data={
        "name": basil.name, "icon": basil.icon, "category": basil.category, "sort_order": basil.sort_order,
        "active": "1", "csrf_token": token,
    })
    db_session.expire_all()
    assert _pizza(db_session, admin.id, "Margherita").vegetarian is False


def test_new_ingredient_vegetarian_flag(client, db_session, admin):
    login(client, "admin@test.at", "geheim123")
    token = csrf_from(client, "/ingredients")
    client.post("/ingredients", data={"name": "Tofu", "category": "other", "vegetarian": "1", "csrf_token": token})
    client.post("/ingredients", data={"name": "Lachs", "category": "fish", "csrf_token": token})
    by_name = {i.name: i for i in db_session.scalars(select(Ingredient).where(Ingredient.owner_id == admin.id))}
    assert by_name["Tofu"].vegetarian is True
    assert by_name["Lachs"].vegetarian is False


def test_reorder_pizzas(client, db_session, admin):
    login(client, "admin@test.at", "geheim123")
    ids = _pizza_ids(db_session, admin.id)
    new_order = [ids[-1], *ids[:-1]]

    token = csrf_from(client, "/dishes/pizza")
    response = client.post("/dishes/pizza/reorder", json={"ids": new_order}, headers={"X-CSRF-Token": token})
    assert response.status_code == 200
    db_session.expire_all()
    assert _pizza_ids(db_session, admin.id) == new_order

    # Ohne CSRF-Header abgelehnt
    assert client.post("/dishes/pizza/reorder", json={"ids": ids}).status_code == 400


def test_reorder_ignores_other_tenants_pizzas(client, db_session, admin):
    other = User(email="kollege@test.at", name="Kollege", password_hash=hash_password("geheim123"),
                 status="approved")
    db_session.add(other)
    db_session.flush()
    seed_catalog(db_session, other.id)
    db_session.commit()
    before = {p.id: p.sort_order for p in db_session.scalars(select(Product).where(Product.owner_id == other.id))}

    login(client, "admin@test.at", "geheim123")
    token = csrf_from(client, "/dishes/pizza")
    client.post("/dishes/pizza/reorder", json={"ids": list(reversed(before))}, headers={"X-CSRF-Token": token})

    db_session.expire_all()
    after = {p.id: p.sort_order for p in db_session.scalars(select(Product).where(Product.owner_id == other.id))}
    assert after == before
    # Fremde Pizza auch nicht bearbeitbar
    assert client.get(f"/dishes/pizza/{next(iter(before))}").status_code == 404
