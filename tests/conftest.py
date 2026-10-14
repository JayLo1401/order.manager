import os
import re

os.environ.setdefault("LOG_DIR", "./data/logs")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401
from app.auth.security import hash_password  # noqa: E402
from app.catalog.defaults import seed_catalog  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    yield session
    app.dependency_overrides.clear()
    session.close()


@pytest.fixture()
def client(db_session):
    return TestClient(app, base_url="http://bestellung.test")


@pytest.fixture()
def admin(db_session):
    user = User(email="admin@test.at", name="Admin", password_hash=hash_password("geheim123"),
                role="superuser", status="approved")
    db_session.add(user)
    db_session.flush()
    seed_catalog(db_session, user.id)
    db_session.commit()
    return user


def csrf_from(client: TestClient, path: str) -> str:
    response = client.get(path)
    match = CSRF_RE.search(response.text)
    assert match, f"Kein CSRF-Token auf {path}"
    return match.group(1)


def login(client: TestClient, email: str, password: str):
    token = csrf_from(client, "/login")
    return client.post("/login", data={"email": email, "password": password, "csrf_token": token},
                       follow_redirects=False)
