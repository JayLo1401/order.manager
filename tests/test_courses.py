import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.catalog import Product, ProductOption
from app.models.event import Event, Order
from tests.conftest import csrf_from, login


@pytest.fixture()
def setup(client, db_session, admin):
    """Bestell-Link mit Vor-, Haupt- und Nachspeise, eingeloggter Gast (Limit 1 pro Gang)."""
    login(client, "admin@test.at", "geheim123")
    client.post("/link/create", data={"csrf_token": csrf_from(client, "/link")})
    event = db_session.scalar(select(Event))
    guest = TestClient(client.app, base_url="http://bestellung.test")
    guest.post(f"/o/{event.token}/join", data={"name": "Gast", "csrf_token": csrf_from(guest, f"/o/{event.token}")})
    set_courses(client, ["starter", "main", "dessert"])
    return event, guest


def set_courses(client, courses, main_kind="pizza"):
    return client.post("/link/courses", data={
        "courses": courses, "main_kind": main_kind, "next": "/kitchen", "csrf_token": csrf_from(client, "/link"),
    }, follow_redirects=False)


def switch(client, course):
    return client.post("/link/course", data={
        "course": course, "next": "/kitchen", "csrf_token": csrf_from(client, "/link"),
    }, follow_redirects=False)


def _product(db_session, admin, name):
    return db_session.scalar(select(Product).where(Product.owner_id == admin.id, Product.name == name))


def _option(db_session, admin, name):
    return db_session.scalar(select(ProductOption).where(ProductOption.owner_id == admin.id, ProductOption.name == name))


def _orders(db_session):
    db_session.expire_all()
    return db_session.scalars(select(Order).order_by(Order.id)).all()


def test_defaults_for_starter_and_dessert(db_session, admin):
    soup = _product(db_session, admin, "Kürbiscremesuppe")
    pancake = _product(db_session, admin, "Eispalatschinke")
    assert soup.kind == "starter" and not soup.choice_required
    assert pancake.kind == "dessert" and pancake.choice_required
    options = {o.name: o for o in pancake.options}
    assert set(options) == {"Vanilleeis", "Erdbeereis", "mit Schokosauce"}
    assert options["Vanilleeis"].option_group == "shape" and options["mit Schokosauce"].option_group == "extra"
    assert all(o.kind == "dessert" and not o.all_products for o in options.values())


def test_new_event_defaults_to_pizza_main_course(client, db_session, admin):
    login(client, "admin@test.at", "geheim123")
    client.post("/link/create", data={"csrf_token": csrf_from(client, "/link")})
    event = db_session.scalar(select(Event))
    assert event.courses == ["main"] and event.main_kind == "pizza" and event.current_course == "main"


def test_course_flow(client, db_session, admin, setup):
    event, guest = setup
    soup = _product(db_session, admin, "Kürbiscremesuppe")
    margherita = _product(db_session, admin, "Margherita")
    pancake = _product(db_session, admin, "Eispalatschinke")
    token = csrf_from(guest, f"/o/{event.token}/menu")

    def order(**data):
        guest.post(f"/o/{event.token}/order", data={"csrf_token": token, **data})
        return _orders(db_session)

    # Vorspeise: nur die Suppe auf der Karte, keine Pizza bestellbar
    switch(client, "starter")
    menu = guest.get(f"/o/{event.token}/menu").text
    assert "Kürbiscremesuppe" in menu and "Margherita" not in menu and "Wunschpizza" not in menu
    assert guest.get(f"/o/{event.token}/custom", follow_redirects=False).headers["location"].endswith("/menu")
    assert order(product_id=margherita.id) == []
    orders = order(product_id=soup.id)
    assert [(o.item_name, o.course) for o in orders] == [("Kürbiscremesuppe", "starter")]

    # Geschlossen: nichts bestellbar
    switch(client, "")
    assert guest.get(f"/o/{event.token}/api/status").json()["can_order_more"] is False
    assert guest.get(f"/o/{event.token}/menu", follow_redirects=False).status_code == 303
    assert len(order(product_id=soup.id)) == 1

    # Hauptspeise: Limit gilt pro Gang -> Pizza trotz Suppe bestellbar
    switch(client, "main")
    status = guest.get(f"/o/{event.token}/status").text
    assert "Jetzt Pizza bestellen" in status
    assert guest.get(f"/o/{event.token}/api/status").json()["current_course"] == "main"
    orders = order(product_id=margherita.id)
    assert orders[-1].course == "main"
    assert len(order(product_id=margherita.id)) == 2  # Limit fuer die Hauptspeise erreicht

    # Nachspeise: Eissorte ist Pflicht, nur eine Sorte, Schokosauce optional
    switch(client, "dessert")
    menu = guest.get(f"/o/{event.token}/menu").text
    assert "Eispalatschinke" in menu and 'data-choice-required="1"' in menu and "Vanilleeis" in menu
    vanilla, strawberry = _option(db_session, admin, "Vanilleeis"), _option(db_session, admin, "Erdbeereis")
    chocolate = _option(db_session, admin, "mit Schokosauce")
    assert len(order(product_id=pancake.id)) == 2
    assert len(order(product_id=pancake.id, option_ids=[chocolate.id])) == 2
    assert len(order(product_id=pancake.id, option_ids=[vanilla.id, strawberry.id])) == 2
    orders = order(product_id=pancake.id, option_ids=[chocolate.id, strawberry.id])
    assert orders[-1].course == "dessert"
    assert [o["name"] for o in orders[-1].options] == ["Erdbeereis", "mit Schokosauce"]

    # Kueche sieht den Gang
    data = client.get("/kitchen/api/orders").json()
    assert data["event"]["courses"] == ["starter", "main", "dessert"]
    assert data["event"]["current_course"] == "dessert"
    assert [o["course_label"] for o in data["orders"]] == ["Vorspeise", "Hauptspeise", "Nachspeise"]
    assert data["orders"][2]["course_noun"] == "Nachspeise"


def test_dessert_options_not_offered_for_pizza(client, db_session, admin, setup):
    event, guest = setup
    margherita = _product(db_session, admin, "Margherita")
    vanilla = _option(db_session, admin, "Vanilleeis")
    switch(client, "main")
    assert "Vanilleeis" not in guest.get(f"/o/{event.token}/menu").text
    token = csrf_from(guest, f"/o/{event.token}/menu")
    guest.post(f"/o/{event.token}/order", data={"product_id": margherita.id, "option_ids": [vanilla.id],
                                                "csrf_token": token})
    assert _orders(db_session) == []


def test_other_main_dishes_instead_of_pizza(client, db_session, admin, setup):
    event, guest = setup
    set_courses(client, ["main"], main_kind="main")
    switch(client, "main")

    # Noch keine Hauptgerichte angelegt -> Hinweis statt Pizza/Wunschpizza
    menu = guest.get(f"/o/{event.token}/menu").text
    assert "nichts zu bestellen" in menu and "Margherita" not in menu and "Wunschpizza" not in menu

    client.post("/dishes/main", data={
        "name": "Gulasch", "icon": "🍲", "description": "", "active": "1",
        "csrf_token": csrf_from(client, "/dishes/main/new"),
    })
    goulash = _product(db_session, admin, "Gulasch")
    assert goulash.kind == "main"
    assert "Gulasch" in guest.get(f"/o/{event.token}/menu").text

    token = csrf_from(guest, f"/o/{event.token}/menu")
    ingredient_ids = [i.id for i in _product(db_session, admin, "Margherita").ingredients]
    guest.post(f"/o/{event.token}/order", data={"ingredient_ids": ingredient_ids, "csrf_token": token})
    assert _orders(db_session) == []  # keine Wunschpizza
    guest.post(f"/o/{event.token}/order", data={"product_id": goulash.id, "csrf_token": token})
    orders = _orders(db_session)
    assert [(o.item_name, o.course) for o in orders] == [("Gulasch", "main")]
    # Zutaten-Knopf nur bei Pizza
    assert 'id="stock-open"' not in client.get("/kitchen").text


def test_course_settings_validation(client, db_session, admin, setup):
    event, guest = setup
    switch(client, "starter")
    # Vorspeise abwaehlen, waehrend sie laeuft -> Bestellungen geschlossen
    set_courses(client, ["main", "dessert"])
    db_session.refresh(event)
    assert event.courses == ["main", "dessert"] and event.current_course is None
    # Gang, den es heute nicht gibt, kann nicht freigegeben werden
    switch(client, "starter")
    db_session.refresh(event)
    assert event.current_course is None
    # Mindestens ein Gang
    set_courses(client, [])
    db_session.refresh(event)
    assert event.courses == ["main", "dessert"]

    kitchen = client.get("/kitchen").text
    assert 'value="dessert"' in kitchen and 'value="starter"' not in kitchen.split('id="courses-modal"')[0]


def test_extra_order_is_per_course(client, db_session, admin, setup):
    event, guest = setup
    soup = _product(db_session, admin, "Kürbiscremesuppe")
    margherita = _product(db_session, admin, "Margherita")
    token = csrf_from(guest, f"/o/{event.token}/menu")
    switch(client, "starter")
    guest.post(f"/o/{event.token}/order", data={"product_id": soup.id, "csrf_token": token})
    order = client.get("/kitchen/api/orders").json()["orders"][0]
    headers = {"X-CSRF-Token": csrf_from(client, "/kitchen")}
    response = client.post(f"/kitchen/api/guests/{order['guest_id']}/extra", json={"delta": 1, "course": "starter"},
                           headers=headers)
    assert response.json() == {"guest_id": order["guest_id"], "course": "starter", "extra_orders": 1}
    assert "Es ist noch Vorspeise übrig" in guest.get(f"/o/{event.token}/status").text

    # Nachschlag fuer die Vorspeise gilt nicht fuer die Hauptspeise
    switch(client, "main")
    guest.post(f"/o/{event.token}/order", data={"product_id": margherita.id, "csrf_token": token})
    guest.post(f"/o/{event.token}/order", data={"product_id": margherita.id, "csrf_token": token})
    assert [o.course for o in _orders(db_session)] == ["starter", "main"]

    assert client.post(f"/kitchen/api/guests/{order['guest_id']}/extra", json={"delta": 1, "course": "x"},
                       headers=headers).status_code == 400


def test_dish_admin_per_kind(client, db_session, admin):
    login(client, "admin@test.at", "geheim123")
    pancake = _product(db_session, admin, "Eispalatschinke")
    page = client.get("/dishes/dessert").text
    assert "Eispalatschinke" in page and "Margherita" not in page
    assert client.get("/dishes/bogus").status_code == 404
    assert client.get(f"/dishes/pizza/{pancake.id}").status_code == 404
    assert client.get(f"/dishes/dessert/{pancake.id}").status_code == 200
    vanilla = _option(db_session, admin, "Vanilleeis")
    assert f"/options/{vanilla.id}" in client.get("/options?kind=dessert").text
    assert f"/options/{vanilla.id}" not in client.get("/options").text

    # Pflicht-Auswahl abschalten; Optionen anderer Arten werden nicht zugeordnet
    calzone = _option(db_session, admin, "Calzone")
    client.post(f"/dishes/dessert/{pancake.id}", data={
        "name": pancake.name, "icon": pancake.icon, "description": "", "active": "1",
        "option_ids": [vanilla.id, calzone.id], "csrf_token": csrf_from(client, f"/dishes/dessert/{pancake.id}"),
    })
    db_session.expire_all()
    pancake = db_session.get(Product, pancake.id)
    assert not pancake.choice_required
    assert [o.name for o in pancake.options] == ["Vanilleeis"]


def test_guest_skips_starter(client, db_session, admin, setup):
    event, guest = setup
    token = csrf_from(guest, f"/o/{event.token}/menu")

    # Hauptspeise kann man nicht auslassen
    guest.post(f"/o/{event.token}/order", data={"skip": "1", "csrf_token": token})
    assert _orders(db_session) == []

    switch(client, "starter")
    assert "Ich möchte keine Vorspeise" in guest.get(f"/o/{event.token}/menu").text
    guest.post(f"/o/{event.token}/order", data={"skip": "1", "csrf_token": token})
    orders = _orders(db_session)
    assert [(o.item_name, o.course, o.is_skip) for o in orders] == [("Keine Vorspeise", "starter", True)]
    # Zaehlt als Bestellung fuer den Gang -> keine erneute Aufforderung
    assert guest.get(f"/o/{event.token}/api/status").json()["can_order_more"] is False
    assert "die Küche weiß Bescheid" in guest.get(f"/o/{event.token}/status").text

    kitchen_order = client.get("/kitchen/api/orders").json()["orders"][0]
    assert kitchen_order["is_skip"] is True
    headers = {"X-CSRF-Token": csrf_from(client, "/kitchen")}
    response = client.post(f"/kitchen/api/orders/{kitchen_order['id']}/status", json={"status": "done"}, headers=headers)
    assert response.json()["status"] == "done"

    # Danach normal mit der Hauptspeise weiter
    switch(client, "main")
    assert "Jetzt Pizza bestellen" in guest.get(f"/o/{event.token}/status").text
