from fastapi import Depends, Form, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.security import generate_token
from app.database import get_db
from app.models.user import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    return db.get(User, user_id)


def require_login(request: Request, user: User | None = Depends(get_current_user)) -> User:
    if user is None or user.status != "approved":
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={request.url.path}"},
        )
    return user


def require_login_api(request: Request, user: User | None = Depends(get_current_user)) -> User:
    """Wie require_login, aber fuer JSON-Endpunkte (401 statt Redirect)."""
    if user is None or user.status != "approved":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet")
    return user


def require_superuser(user: User = Depends(require_login)) -> User:
    if not user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Nur fuer den Haupt-Admin")
    return user


def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = generate_token()
        request.session["csrf_token"] = token
    return token


def csrf_token_valid(request: Request, token: str | None) -> bool:
    expected = request.session.get("csrf_token")
    return bool(expected) and token == expected


def verify_csrf(request: Request, csrf_token: str = Form(...)) -> None:
    if not csrf_token_valid(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ungueltiges Formular (CSRF)")


def verify_csrf_header(request: Request, x_csrf_token: str | None = Header(default=None)) -> None:
    """CSRF-Pruefung fuer fetch()-Aufrufe (Token im Header X-CSRF-Token)."""
    if not csrf_token_valid(request, x_csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ungueltige Anfrage (CSRF)")
