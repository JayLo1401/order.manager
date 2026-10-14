import datetime
import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.catalog import Ingredient, Product
from app.models.event import Event, Order
from app.models.settings import HostSettings
from tests.conftest import csrf_from, login


def _create_link(client, db_session, admin) -> Event:
    login(client, "admin@test.at", "geheim123")
    token = csrf_from(client, "/link")
    assert client.post("/link/create", data={"csrf_token": token}, follow_redirects=False).status_code == 303
    return db_session.scalar(select(Event).where(Event.owner_id == admin.id))


def _guest(client) -> TestClient:
    return TestClient(client.app, base_url="http://bestellung.test")


def _join(guest: TestClient, event: Event, name="Anna", table_no=""):
    token = csrf_from(guest, f"/o/{event.token}")
    return guest.post(f"/o/{event.token}/join", data={"name": name, "table_no": table_no, "csrf_token": token},
                      follow_redirects=False)


def test_link_page_shows_qr(client, db_session, admin):
    event = _create_link(client, db_session, admin)
    response = client.get("/link")
    assert event.token in response.text
    assert "<svg" in response.text
    assert client.get("/link/qr.png").headers["content-type"] == "image/png"


def test_qr_svg_scales_instead_of_cropping():
    from app.events.service import qr_svg

    svg = qr_svg("https://bestellung.example/o/abcdefghijklmnopqrstuvwxyz012345")
    head = svg[:svg.index(">")]
    assert "viewBox" in head
    assert "width=" not in head and "height=" not in head


def test_guest_orders_preset_and_kitchen_completes(client, db_session, admin):
    event = _create_link(client, db_session, admin)
    guest = _guest(client)

    assert _join(guest, event).headers["location"] == f"/o/{event.token}/menu"
    menu = guest.get(f"/o/{event.token}/menu")
    assert "Margherita" in menu.text

    margherita = db_session.scalar(select(Product).where(Product.owner_id == admin.id, Product.name == "Margherita"))
    token = csrf_from(guest, f"/o/{event.token}/menu")
    response = guest.post(f"/o/{event.token}/order", data={"product_id": margherita.id, "note": "knusprig",
                                                           "csrf_token": token}, follow_redirects=False)
    assert response.headers["location"].endswith("/status?ok=1")
    status = guest.get(response.headers["location"])
    assert "Erfolgreich bestellt" in status.text

    # Standard: nur eine Pizza pro Gast
    response = guest.post(f"/o/{event.token}/order", data={"product_id": margherita.id, "csrf_token": token},
                          follow_redirects=False)
    assert db_session.scalars(select(Order)).all().__len__() == 1
    assert guest.get(f"/o/{event.token}/menu", follow_redirects=False).status_code == 303

    # Kueche
    data = client.get("/kitchen/api/orders").json()
    assert len(data["orders"]) == 1
    order = data["orders"][0]
    assert order["guest"] == "Anna" and order["note"] == "knusprig" and order["number"] == 1
    assert order["vegetarian"] is True
    assert "Vegetarisch" in status.text

    kitchen_csrf = csrf_from(client, "/kitchen")
    headers = {"X-CSRF-Token": kitchen_csrf}
    assert client.post(f"/kitchen/api/orders/{order['id']}/status", json={"status": "in_progress"},
                       headers=headers).json()["status"] == "in_progress"
    assert guest.get(f"/o/{event.token}/api/status").json()["orders"][0]["status"] == "in_progress"
    assert client.post(f"/kitchen/api/orders/{order['id']}/status", json={"status": "done"},
                       headers=headers).status_code == 200
    assert guest.get(f"/o/{event.token}/api/status").json()["orders"][0]["status"] == "done"
    assert "fertig" in guest.get(f"/o/{event.token}/status").text

    # Ohne CSRF-Header abgelehnt
    assert client.post(f"/kitchen/api/orders/{order['id']}/status", json={"status": "in_progress"}).status_code == 400


def test_custom_pizza_respects_limits_and_inactive(client, db_session, admin):
    host_settings = db_session.scalar(select(HostSettings).where(HostSettings.owner_id == admin.id))
    host_settings.max_custom_ingredients = 2
    host_settings.max_orders_per_guest = 0
    db_session.commit()
    event = _create_link(client, db_session, admin)
    guest = _guest(client)
    _join(guest, event)

    ingredients = db_session.scalars(select(Ingredient).where(Ingredient.owner_id == admin.id)).all()
    ids = [i.id for i in ingredients[:3]]
    token = csrf_from(guest, f"/o/{event.token}/custom")
    guest.post(f"/o/{event.token}/order", data={"ingredient_ids": ids, "csrf_token": token})
    assert db_session.scalars(select(Order)).all() == []

    ingredients[0].active = False
    db_session.commit()
    guest.post(f"/o/{event.token}/order", data={"ingredient_ids": ids[:2], "csrf_token": token})
    orders = db_session.scalars(select(Order)).all()
    assert len(orders) == 1
    assert orders[0].is_custom and [i["name"] for i in orders[0].ingredients] == [ingredients[1].name]


def test_duplicate_guest_name_rejected(client, db_session, admin):
    event = _create_link(client, db_session, admin)
    _join(_guest(client), event, name="Ben")
    response = _join(_guest(client), event, name="ben")
    assert response.status_code == 200
    assert "schon vergeben" in response.text


def test_table_mode(client, db_session, admin):
    host_settings = db_session.scalar(select(HostSettings).where(HostSettings.owner_id == admin.id))
    host_settings.guest_identity = "table"
    db_session.commit()
    event = _create_link(client, db_session, admin)
    assert 'name="table_no"' in _guest(client).get(f"/o/{event.token}").text
    response = _join(_guest(client), event, name="", table_no="7")
    assert response.status_code == 303


def test_link_only_valid_today(client, db_session, admin):
    event = _create_link(client, db_session, admin)
    event.day = datetime.date.today() - datetime.timedelta(days=1)
    db_session.commit()
    response = _guest(client).get(f"/o/{event.token}")
    assert response.status_code == 410
    assert "abgelaufen" in response.text


def test_guest_cancel(client, db_session, admin):
    event = _create_link(client, db_session, admin)
    guest = _guest(client)
    _join(guest, event)
    product = db_session.scalar(select(Product).where(Product.owner_id == admin.id))
    token = csrf_from(guest, f"/o/{event.token}/menu")
    guest.post(f"/o/{event.token}/order", data={"product_id": product.id, "csrf_token": token})
    order = db_session.scalar(select(Order))
    guest.post(f"/o/{event.token}/orders/{order.id}/cancel", data={"csrf_token": token})
    db_session.refresh(order)
    assert order.status == "cancelled"
    # Nach Storno darf wieder bestellt werden
    assert guest.get(f"/o/{event.token}/menu", follow_redirects=False).status_code == 200


def test_guest_host_only_serves_guest_pages(client, db_session, admin, monkeypatch):
    from app.config import settings

    event = _create_link(client, db_session, admin)
    monkeypatch.setattr(settings, "guest_base_url", "https://pizza.test")
    monkeypatch.setattr(settings, "admin_base_url", "https://bestellung.test")
    guest = TestClient(client.app, base_url="https://pizza.test")
    response = guest.get("/kitchen", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://bestellung.test/kitchen"
    assert guest.get(f"/o/{event.token}").status_code == 200
    # Link zeigt auf die Gaeste-Domain
    assert re.search(rf"https://pizza\.test/o/{event.token}", client.get("/link").text)
