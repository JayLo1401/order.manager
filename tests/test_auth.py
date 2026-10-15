from sqlalchemy import select

from app.models.catalog import Ingredient, Product
from app.models.user import User
from tests.conftest import csrf_from, login


def test_dashboard_requires_login(client, admin):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_register_requires_admin_approval(client, admin, db_session):
    token = csrf_from(client, "/register")
    response = client.post("/register", data={
        "name": "Maria", "email": "Maria@Test.at", "password": "pizza1234",
        "password_repeat": "pizza1234", "csrf_token": token,
    })
    assert response.status_code == 200
    assert "Freischalt" in response.text or "freigeschaltet" in response.text

    response = login(client, "maria@test.at", "pizza1234")
    assert response.status_code == 400
    assert "Freischaltung" in response.text

    maria = db_session.scalar(select(User).where(User.email == "maria@test.at"))
    assert maria.status == "pending"

    # Admin schaltet frei -> Standard-Katalog wird angelegt
    admin_client = client.__class__(client.app, base_url="http://bestellung.test")
    assert login(admin_client, "admin@test.at", "geheim123").status_code == 303
    token = csrf_from(admin_client, "/admin/users")
    response = admin_client.post(f"/admin/users/{maria.id}/approve", data={"csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303

    db_session.refresh(maria)
    assert maria.status == "approved"
    assert db_session.scalar(select(Ingredient.id).where(Ingredient.owner_id == maria.id)) is not None
    assert db_session.scalar(select(Product.id).where(Product.owner_id == maria.id)) is not None

    assert login(client, "maria@test.at", "pizza1234").status_code == 303


def test_member_cannot_open_admin(client, admin, db_session):
    from app.auth.security import hash_password

    db_session.add(User(email="m@test.at", name="M", password_hash=hash_password("geheim123"), status="approved"))
    db_session.commit()
    login(client, "m@test.at", "geheim123")
    assert client.get("/admin/users").status_code == 403


def test_open_redirect_blocked(client, admin):
    token = csrf_from(client, "/login")
    response = client.post("/login", data={
        "email": "admin@test.at", "password": "geheim123", "next": "//evil.example", "csrf_token": token,
    }, follow_redirects=False)
    assert response.headers["location"] == "/"


def test_version_in_healthz_and_footer(client, admin):
    from app import __version__

    assert client.get("/healthz").json() == {"ok": True, "version": __version__}
    login(client, "admin@test.at", "geheim123")
    assert f"v{__version__}" in client.get("/settings").text
