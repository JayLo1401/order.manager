import base64

import pytest

from app.config import settings
from tests.conftest import csrf_from, login

AUTH = ("radio", "geheim-radio")


@pytest.fixture()
def api(monkeypatch, admin):
    monkeypatch.setattr(settings, "api_user", AUTH[0])
    monkeypatch.setattr(settings, "api_password", AUTH[1])
    monkeypatch.setattr(settings, "api_owner_email", admin.email)


def test_api_disabled_without_password(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "api_password", "")
    assert client.get("/api/v1/today", auth=AUTH).status_code == 404


def test_api_requires_basic_auth(client, api):
    response = client.get("/api/v1/today")
    assert response.status_code == 401 and response.headers["www-authenticate"].startswith("Basic")
    assert client.get("/api/v1/today", auth=("radio", "falsch")).status_code == 401
    assert client.get("/api/v1/today", auth=("admin@test.at", "geheim123")).status_code == 401


def test_api_without_event(client, api):
    data = client.get("/api/v1/today", auth=AUTH).json()
    assert data["active"] is False and "qr_svg" not in data


def test_api_with_event_and_course_status(client, db_session, admin, api):
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
