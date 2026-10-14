import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.catalog import Product, ProductOption
from app.models.event import Event, Order
from app.models.settings import HostSettings
from tests.conftest import csrf_from, login


@pytest.fixture()
def setup(client, db_session, admin):
    """Gastgeber mit Bestell-Link, eingeloggter Gast, unbegrenzte Bestellungen."""
    db_session.scalar(select(HostSettings).where(HostSettings.owner_id == admin.id)).max_orders_per_guest = 0
    db_session.commit()
    login(client, "admin@test.at", "geheim123")
    client.post("/link/create", data={"csrf_token": csrf_from(client, "/link")})
    event = db_session.scalar(select(Event))
    guest = TestClient(client.app, base_url="http://bestellung.test")
    guest.post(f"/o/{event.token}/join", data={"name": "Gast", "csrf_token": csrf_from(guest, f"/o/{event.token}")})
    return event, guest


def _pizza(db_session, admin, name):
    return db_session.scalar(select(Product).where(Product.owner_id == admin.id, Product.name == name))


def _create_option(client, **data):
    data = {"icon": "", "description": "", "option_group": "extra", **data}
    data["csrf_token"] = csrf_from(client, "/options")
    return client.post("/options", data=data, follow_redirects=False)


def test_calzone_is_seeded(db_session, admin):
    calzone = db_session.scalar(select(ProductOption).where(ProductOption.owner_id == admin.id))
    assert calzone.name == "Calzone" and calzone.all_products and calzone.option_group == "shape"


def test_order_with_options_and_rules(client, db_session, admin, setup):
    event, guest = setup
    margherita = _pizza(db_session, admin, "Margherita")
    salami = _pizza(db_session, admin, "Salami")
    calzone = db_session.scalar(select(ProductOption).where(ProductOption.name == "Calzone"))

    # Sternpizza (Form, nur Margherita) und Kaeserand (Extra, alle)
    response = _create_option(client, name="Sternpizza", option_group="shape")
    star = db_session.scalar(select(ProductOption).where(ProductOption.name == "Sternpizza"))
    assert response.headers["location"] == f"/options/{star.id}"  # direkt zur Zuordnung
    client.post(f"/options/{star.id}", data={
        "name": "Sternpizza", "icon": "⭐", "description": "", "option_group": "shape", "active": "1",
        "product_ids": [margherita.id], "csrf_token": csrf_from(client, f"/options/{star.id}"),
    })
    _create_option(client, name="Käserand", all_products="1")
    cheese = db_session.scalar(select(ProductOption).where(ProductOption.name == "Käserand"))

    menu = guest.get(f"/o/{event.token}/menu").text
    assert "Wie hättest du sie gern?" in menu and "Sternpizza" in menu
    mapping = json.loads(re.search(r'data-product-options="([^"]+)"', menu).group(1).replace("&#34;", '"'))
    assert star.id in mapping[str(margherita.id)]
    assert star.id not in mapping[str(salami.id)]
    assert calzone.id in mapping[str(salami.id)]

    token = csrf_from(guest, f"/o/{event.token}/menu")

    def order(**data):
        guest.post(f"/o/{event.token}/order", data={"csrf_token": token, **data})
        return db_session.scalars(select(Order).order_by(Order.id)).all()

    # Margherita als Sternpizza mit Kaeserand -> ok, Form zuerst
    orders = order(product_id=margherita.id, option_ids=[cheese.id, star.id])
    assert [o["name"] for o in orders[-1].options] == ["Sternpizza", "Käserand"]

    # Sternpizza bei Salami nicht erlaubt
    assert len(order(product_id=salami.id, option_ids=[star.id])) == 1
    # Zwei Formen gleichzeitig nicht erlaubt
    assert len(order(product_id=margherita.id, option_ids=[star.id, calzone.id])) == 1
    # Wunschpizza: Sternpizza (manuell zugeordnet) nicht, Calzone schon
    ingredient_ids = [i.id for i in margherita.ingredients]
    assert len(order(ingredient_ids=ingredient_ids, option_ids=[star.id])) == 1
    orders = order(ingredient_ids=ingredient_ids, option_ids=[calzone.id])
    assert orders[-1].is_custom and orders[-1].options[0]["name"] == "Calzone"
    custom_page = guest.get(f"/o/{event.token}/custom").text
    assert "Calzone" in custom_page and "Sternpizza" not in custom_page

    # Kueche sieht die Optionen
    kitchen_orders = client.get("/kitchen/api/orders").json()["orders"]
    assert kitchen_orders[0]["options"][0]["name"] == "Sternpizza"

    # Inaktive Option ist nicht mehr bestellbar
    client.post(f"/options/{calzone.id}/toggle", data={"csrf_token": csrf_from(client, "/options")})
    assert len(order(product_id=salami.id, option_ids=[calzone.id])) == 2


def test_assign_option_from_pizza_form(client, db_session, admin):
    login(client, "admin@test.at", "geheim123")
    _create_option(client, name="Extra knusprig")
    crispy = db_session.scalar(select(ProductOption).where(ProductOption.name == "Extra knusprig"))
    salami = _pizza(db_session, admin, "Salami")
    client.post(f"/pizzas/{salami.id}", data={
        "name": salami.name, "icon": salami.icon, "description": "", "active": "1",
        "ingredient_ids": [i.id for i in salami.ingredients], "option_ids": [crispy.id],
        "csrf_token": csrf_from(client, f"/pizzas/{salami.id}"),
    })
    db_session.expire_all()
    assert [p.name for p in db_session.get(ProductOption, crispy.id).products] == ["Salami"]


def test_options_are_tenant_scoped(client, db_session, admin):
    from app.auth.security import hash_password
    from app.catalog.defaults import seed_catalog
    from app.models.user import User

    other = User(email="kollege@test.at", name="K", password_hash=hash_password("geheim123"), status="approved")
    db_session.add(other)
    db_session.flush()
    seed_catalog(db_session, other.id)
    db_session.commit()
    foreign = db_session.scalar(select(ProductOption).where(ProductOption.owner_id == other.id))

    login(client, "admin@test.at", "geheim123")
    assert client.get(f"/options/{foreign.id}").status_code == 404
    page = client.get("/options").text
    assert f"/options/{foreign.id}" not in page
    own = db_session.scalar(select(ProductOption).where(ProductOption.owner_id == admin.id))
    assert f"/options/{own.id}" in page
