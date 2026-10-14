from sqlalchemy import select

from app.auth.security import hash_password
from app.catalog.defaults import seed_catalog
from app.models.catalog import Product
from app.models.user import User
from tests.conftest import csrf_from, login


def _pizza_ids(db_session, owner_id):
    return [p.id for p in db_session.scalars(
        select(Product).where(Product.owner_id == owner_id).order_by(Product.sort_order)
    )]


def test_reorder_pizzas(client, db_session, admin):
    login(client, "admin@test.at", "geheim123")
    ids = _pizza_ids(db_session, admin.id)
    new_order = [ids[-1], *ids[:-1]]

    token = csrf_from(client, "/pizzas")
    response = client.post("/pizzas/reorder", json={"ids": new_order}, headers={"X-CSRF-Token": token})
    assert response.status_code == 200
    db_session.expire_all()
    assert _pizza_ids(db_session, admin.id) == new_order

    # Ohne CSRF-Header abgelehnt
    assert client.post("/pizzas/reorder", json={"ids": ids}).status_code == 400


def test_reorder_ignores_other_tenants_pizzas(client, db_session, admin):
    other = User(email="kollege@test.at", name="Kollege", password_hash=hash_password("geheim123"),
                 status="approved")
    db_session.add(other)
    db_session.flush()
    seed_catalog(db_session, other.id)
    db_session.commit()
    before = {p.id: p.sort_order for p in db_session.scalars(select(Product).where(Product.owner_id == other.id))}

    login(client, "admin@test.at", "geheim123")
    token = csrf_from(client, "/pizzas")
    client.post("/pizzas/reorder", json={"ids": list(reversed(before))}, headers={"X-CSRF-Token": token})

    db_session.expire_all()
    after = {p.id: p.sort_order for p in db_session.scalars(select(Product).where(Product.owner_id == other.id))}
    assert after == before
    # Fremde Pizza auch nicht bearbeitbar
    assert client.get(f"/pizzas/{next(iter(before))}").status_code == 404
