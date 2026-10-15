import base64

from app.auth.security import hash_password
from app.catalog.defaults import seed_catalog
from app.models.user import User
from tests.conftest import csrf_from, login

AUTH = ("admin@test.at", "geheim123")


def _colleague(db_session, status="approved"):
    user = User(email="kollege@test.at", name="Kollege", password_hash=hash_password("geheim456"), status=status)
    db_session.add(user)
    db_session.flush()
    seed_catalog(db_session, user.id)
    db_session.commit()
    return user


def test_api_requires_valid_login(client, db_session, admin):
    response = client.get("/api/v1/today")
    assert response.status_code == 401 and response.headers["www-authenticate"].startswith("Basic")
    assert client.get("/api/v1/today", auth=("admin@test.at", "falsch")).status_code == 401
    assert client.get("/api/v1/today", auth=("niemand@test.at", "geheim123")).status_code == 401
    # E-Mail ohne Ruecksicht auf Gross-/Kleinschreibung, wie beim Login
    assert client.get("/api/v1/today", auth=("Admin@Test.at", "geheim123")).status_code == 200
    # Noch nicht freigeschaltet -> kein Zugriff
    _colleague(db_session, status="pending")
    assert client.get("/api/v1/today", auth=("kollege@test.at", "geheim456")).status_code == 401


def test_api_without_event(client, admin):
    data = client.get("/api/v1/today", auth=AUTH).json()
    assert data["active"] is False and "qr_svg" not in data


def test_api_with_event_and_course_status(client, db_session, admin):
    login(client, "admin@test.at", "geheim123")
    client.post("/link/create", data={"csrf_token": csrf_from(client, "/link")})
    client.post("/link/courses", data={"courses": ["starter", "main"], "main_kind": "pizza",
                                       "csrf_token": csrf_from(client, "/link")})

    data = client.get("/api/v1/today", auth=AUTH).json()
    assert data["active"] is True and data["title"] == "Pizzaabend" and data["host_name"] == "Admin"
    assert data["status"] == {"code": "main", "label": "Pizzen werden angenommen", "icon": "🍕"}
    assert [c["code"] for c in data["courses"]] == ["starter", "main"]
    assert "/o/" in data["url"] and data["qr_svg"].startswith("<svg")
    assert base64.b64decode(data["qr_png_base64"]).startswith(b"\x89PNG")

    client.post("/link/course", data={"course": "starter", "csrf_token": csrf_from(client, "/link")})
    assert client.get("/api/v1/today", auth=AUTH).json()["status"]["label"] == "Vorspeisen werden angenommen"
    client.post("/link/course", data={"course": "", "csrf_token": csrf_from(client, "/link")})
    assert client.get("/api/v1/today", auth=AUTH).json()["status"]["code"] == "closed"


def test_api_shows_own_event_only(client, db_session, admin):
    _colleague(db_session)
    login(client, "admin@test.at", "geheim123")
    client.post("/link/create", data={"csrf_token": csrf_from(client, "/link")})
    assert client.get("/api/v1/today", auth=AUTH).json()["active"] is True
    # Der Kollege hat heute keinen Bestelltag - und sieht den des Admins nicht
    assert client.get("/api/v1/today", auth=("kollege@test.at", "geheim456")).json()["active"] is False


def test_api_ready_for_pickup(client, db_session, admin):
    import datetime

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.models.catalog import Product
    from app.models.event import Event, Order

    login(client, "admin@test.at", "geheim123")
    client.post("/link/create", data={"csrf_token": csrf_from(client, "/link")})
    client.post("/link/courses", data={"courses": ["starter", "main"], "main_kind": "pizza",
                                       "csrf_token": csrf_from(client, "/link")})
    client.post("/link/course", data={"course": "starter", "csrf_token": csrf_from(client, "/link")})
    event = db_session.scalar(select(Event))
    soup = db_session.scalar(select(Product).where(Product.name == "Kürbiscremesuppe"))

    # Drei Gaeste: zwei Suppen, einer moechte keine Vorspeise
    for name, data in [("Anna", {"product_id": soup.id}), ("Ben", {"product_id": soup.id}), ("Carla", {"skip": "1"})]:
        guest = TestClient(client.app, base_url="http://bestellung.test")
        guest.post(f"/o/{event.token}/join", data={"name": name, "csrf_token": csrf_from(guest, f"/o/{event.token}")})
        guest.post(f"/o/{event.token}/order", data={**data, "csrf_token": csrf_from(guest, f"/o/{event.token}/menu")})

    assert client.get("/api/v1/ready", auth=AUTH).json()["ready"] == []
    headers = {"X-CSRF-Token": csrf_from(client, "/kitchen")}
    for o in client.get("/kitchen/api/orders").json()["orders"]:
        client.post(f"/kitchen/api/orders/{o['id']}/status", json={"status": "done"}, headers=headers)

    data = client.get("/api/v1/ready", auth=AUTH).json()
    assert data["active"] is True
    assert [(r["guest"], r["item_name"], r["course_label"]) for r in data["ready"]] == [
        ("Anna", "Kürbiscremesuppe", "Vorspeise"), ("Ben", "Kürbiscremesuppe", "Vorspeise"),
    ]
    assert len({r["key"] for r in data["ready"]}) == 2 and data["ready"][0]["age_seconds"] < 10

    # Aelter als das Zeitfenster -> nicht mehr dabei
    for order in db_session.scalars(select(Order)):
        order.done_at = order.done_at - datetime.timedelta(minutes=5)
    db_session.commit()
    assert client.get("/api/v1/ready", auth=AUTH).json()["ready"] == []
    assert client.get("/api/v1/ready", auth=("admin@test.at", "falsch")).status_code == 401
