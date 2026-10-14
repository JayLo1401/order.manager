import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.catalog import Ingredient, Product
from app.models.event import Event, Order
from app.models.settings import HostSettings
from tests.conftest import csrf_from, login


@pytest.fixture()
def setup(client, db_session, admin):
    db_session.scalar(select(HostSettings).where(HostSettings.owner_id == admin.id)).max_orders_per_guest = 0
    db_session.commit()
    login(client, "admin@test.at", "geheim123")
    client.post("/link/create", data={"csrf_token": csrf_from(client, "/link")})
    event = db_session.scalar(select(Event))
    guest = TestClient(client.app, base_url="http://bestellung.test")
    guest.post(f"/o/{event.token}/join", data={"name": "Gast", "csrf_token": csrf_from(guest, f"/o/{event.token}")})
    headers = {"X-CSRF-Token": csrf_from(client, "/kitchen")}
    return event, guest, headers


def _ingredient(db_session, admin, name):
    return db_session.scalar(select(Ingredient).where(Ingredient.owner_id == admin.id, Ingredient.name == name))


def test_sold_out_hides_pizzas_and_blocks_orders(client, db_session, admin, setup):
    event, guest, headers = setup
    salami_ing = _ingredient(db_session, admin, "Salami")

    groups = client.get("/kitchen/api/ingredients").json()["groups"]
    assert any(i["name"] == "Salami" and not i["sold_out"] for g in groups for i in g["items"])

    response = client.post(f"/kitchen/api/ingredients/{salami_ing.id}/sold-out", json={"sold_out": True},
                           headers=headers)
    assert response.json()["sold_out_count"] == 1
    assert client.get("/kitchen/api/orders").json()["event"]["sold_out_count"] == 1

    # Pizza "Salami" ist fuer Gaeste weg, Margherita noch da
    menu = guest.get(f"/o/{event.token}/menu").text
    salami = db_session.scalar(select(Product).where(Product.owner_id == admin.id, Product.name == "Salami"))
    assert f'value="{salami.id}"' not in menu
    assert "Margherita" in menu

    # Wunschpizza: Zutat ausgegraut
    custom = guest.get(f"/o/{event.token}/custom").text
    assert f'value="{salami_ing.id}" data-vegetarian="0"\n                   disabled data-sold-out="1"' in custom
    assert "heute aus" in custom

    # Bestellungen mit der Zutat werden abgelehnt (auch per direktem POST)
    token = csrf_from(guest, f"/o/{event.token}/menu")
    guest.post(f"/o/{event.token}/order", data={"product_id": salami.id, "csrf_token": token})
    guest.post(f"/o/{event.token}/order", data={"ingredient_ids": [salami_ing.id], "csrf_token": token})
    assert db_session.scalars(select(Order)).all() == []

    # Zutat ist in der Verwaltung weiterhin aktiv, aber als "heute aus" markiert
    db_session.refresh(salami_ing)
    assert salami_ing.active is True
    assert "heute aus" in client.get("/ingredients").text

    # Wieder da
    client.post(f"/kitchen/api/ingredients/{salami_ing.id}/sold-out", json={"sold_out": False}, headers=headers)
    guest.post(f"/o/{event.token}/order", data={"product_id": salami.id, "csrf_token": token})
    assert len(db_session.scalars(select(Order)).all()) == 1


def test_sold_out_only_for_today(client, db_session, admin, setup):
    event, guest, headers = setup
    salami_ing = _ingredient(db_session, admin, "Salami")
    client.post(f"/kitchen/api/ingredients/{salami_ing.id}/sold-out", json={"sold_out": True}, headers=headers)

    # Naechster Tag = neuer Bestelltag ohne Markierung
    event.day = datetime.date.today() - datetime.timedelta(days=1)
    db_session.commit()
    client.post("/link/create", data={"csrf_token": csrf_from(client, "/link")})
    today = db_session.scalar(select(Event).where(Event.id != event.id))
    assert today.sold_out_ids == set()
    groups = client.get("/kitchen/api/ingredients").json()["groups"]
    assert all(not i["sold_out"] for g in groups for i in g["items"])


def test_sold_out_requires_csrf_and_ownership(client, db_session, admin, setup):
    from app.auth.security import hash_password
    from app.catalog.defaults import seed_catalog
    from app.models.user import User

    event, guest, headers = setup
    salami_ing = _ingredient(db_session, admin, "Salami")
    assert client.post(f"/kitchen/api/ingredients/{salami_ing.id}/sold-out", json={"sold_out": True}).status_code == 400

    other = User(email="kollege@test.at", name="K", password_hash=hash_password("geheim123"), status="approved")
    db_session.add(other)
    db_session.flush()
    seed_catalog(db_session, other.id)
    db_session.commit()
    foreign = db_session.scalar(select(Ingredient).where(Ingredient.owner_id == other.id))
    response = client.post(f"/kitchen/api/ingredients/{foreign.id}/sold-out", json={"sold_out": True}, headers=headers)
    assert response.status_code == 404
