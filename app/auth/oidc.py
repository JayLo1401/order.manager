"""Anmeldung ueber authentik (OpenID Connect), parallel zum Passwort-Login.

Zuordnung ueber die E-Mail-Adresse: gibt es das Konto schon, wird es
angemeldet (sofern freigeschaltet). Unbekannte Adressen werden wie bei
/register als "pending" angelegt und muessen vom Admin freigegeben werden.
"""

import logging

import httpx
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.routes import LOGIN_BLOCK_MESSAGES, safe_next, start_session
from app.auth.security import generate_token, hash_password
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()

_oauth: OAuth | None = None


def get_client():
    global _oauth
    if not settings.oidc_enabled:
        raise HTTPException(status_code=404)
    if _oauth is None:
        _oauth = OAuth()
        _oauth.register(
            "authentik",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    return _oauth.authentik


def _login_error(request: Request, error: str):
    return templates.TemplateResponse(
        request, "auth/login.html", {"next": "", "error": error, "email": ""}, status_code=400
    )


@router.get("/login/oidc")
async def oidc_start(request: Request, next: str | None = None):
    client = get_client()
    request.session["oidc_next"] = safe_next(next)
    try:
        return await client.authorize_redirect(request, str(request.url_for("oidc_callback")))
    except httpx.HTTPError as exc:
        logger.error("OIDC: authentik nicht erreichbar (%s): %s", settings.oidc_issuer, exc)
        return _login_error(request, "authentik ist gerade nicht erreichbar.")


@router.get("/login/oidc/callback")
async def oidc_callback(request: Request, db: Session = Depends(get_db)):
    client = get_client()
    try:
        token = await client.authorize_access_token(request)
        info = token.get("userinfo") or await client.userinfo(token=token)
    except (OAuthError, httpx.HTTPError) as exc:
        logger.warning("OIDC-Anmeldung fehlgeschlagen: %s", exc)
        return _login_error(request, "Anmeldung über authentik fehlgeschlagen.")

    email = (info.get("email") or "").strip().lower()
    if "@" not in email:
        return _login_error(request, "authentik hat keine E-Mail-Adresse übermittelt.")

    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        name = (info.get("name") or info.get("preferred_username") or email.split("@")[0]).strip()
        # Zufaelliges Passwort: das Konto ist nur ueber authentik nutzbar, bis
        # der Admin ein Passwort setzt.
        db.add(User(email=email, name=name, password_hash=hash_password(generate_token()),
                    role="member", status="pending"))
        db.commit()
        return templates.TemplateResponse(request, "auth/registered.html", {"name": name})
    if user.status != "approved":
        return _login_error(request, LOGIN_BLOCK_MESSAGES.get(user.status, "Anmeldung nicht möglich."))

    next_url = request.session.get("oidc_next", "/")
    start_session(request, user)
    return RedirectResponse(safe_next(next_url), status_code=303)
