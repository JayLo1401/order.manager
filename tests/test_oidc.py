from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.auth import oidc
from app.config import settings
from app.models.user import User


@pytest.fixture()
def fake_oidc(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.test/application/o/bestell/")
    monkeypatch.setattr(settings, "oidc_client_id", "client")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")
    client = MagicMock()
    monkeypatch.setattr(oidc, "get_client", lambda: client)
    return client


def callback_as(client, fake_oidc, email: str, name: str = "Maria"):
    fake_oidc.authorize_access_token = AsyncMock(return_value={"userinfo": {"email": email, "name": name}})
    return client.get("/login/oidc/callback", follow_redirects=False)


def test_button_hidden_without_config(client, admin):
    assert "/login/oidc" not in client.get("/login").text
    assert client.get("/login/oidc").status_code == 404


def test_button_shown_with_config(client, admin, fake_oidc):
    assert "Mit authentik anmelden" in client.get("/login").text


def test_known_user_logged_in(client, admin, fake_oidc):
    response = callback_as(client, fake_oidc, "Admin@Test.at")
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert client.get("/", follow_redirects=False).status_code == 200


def test_unknown_user_created_pending(client, admin, fake_oidc, db_session):
    response = callback_as(client, fake_oidc, "neu@test.at", "Neu")
    assert response.status_code == 200
    user = db_session.scalar(select(User).where(User.email == "neu@test.at"))
    assert user.status == "pending" and user.role == "member"

    response = callback_as(client, fake_oidc, "neu@test.at", "Neu")
    assert response.status_code == 400
    assert "Freischaltung" in response.text
    assert client.get("/", follow_redirects=False).status_code == 303
