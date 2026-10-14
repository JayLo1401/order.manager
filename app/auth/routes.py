from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, verify_csrf
from app.auth.security import hash_password, verify_password
from app.database import get_db
from app.models.user import User
from app.templating import flash, templates

router = APIRouter()

MIN_PASSWORD_LENGTH = 8

LOGIN_BLOCK_MESSAGES = {
    "pending": "Dein Konto wartet noch auf die Freischaltung durch den Administrator.",
    "rejected": "Deine Registrierung wurde abgelehnt.",
    "disabled": "Dein Konto ist deaktiviert.",
}


def safe_next(next_url: str | None) -> str:
    # Nur relative Pfade zulassen, sonst waere /login?next=https://boese.example
    # ein offener Redirect.
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/"


def start_session(request: Request, user: User) -> None:
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["role"] = user.role
    request.session["name"] = user.name


@router.get("/login")
def login_form(request: Request, next: str | None = None, user: User | None = Depends(get_current_user)):
    if user is not None and user.status == "approved":
        return RedirectResponse(safe_next(next), status_code=303)
    return templates.TemplateResponse(request, "auth/login.html", {"next": next or "", "error": None, "email": ""})


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    error = None
    if user is None or not verify_password(user.password_hash, password):
        error = "E-Mail oder Passwort ist falsch."
    elif user.status != "approved":
        error = LOGIN_BLOCK_MESSAGES.get(user.status, "Anmeldung nicht möglich.")
    if error:
        return templates.TemplateResponse(
            request, "auth/login.html", {"next": next, "error": error, "email": email}, status_code=400
        )
    start_session(request, user)
    return RedirectResponse(safe_next(next), status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/register")
def register_form(request: Request):
    return templates.TemplateResponse(request, "auth/register.html", {"error": None, "form": {}})


@router.post("/register", dependencies=[Depends(verify_csrf)])
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_repeat: str = Form(...),
    db: Session = Depends(get_db),
):
    name = name.strip()
    email = email.strip().lower()
    error = None
    if not name or "@" not in email:
        error = "Bitte Name und eine gültige E-Mail-Adresse angeben."
    elif len(password) < MIN_PASSWORD_LENGTH:
        error = f"Das Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen haben."
    elif password != password_repeat:
        error = "Die Passwörter stimmen nicht überein."
    elif db.scalar(select(User.id).where(func.lower(User.email) == email)) is not None:
        error = "Diese E-Mail-Adresse ist bereits registriert."
    if error:
        return templates.TemplateResponse(
            request, "auth/register.html", {"error": error, "form": {"name": name, "email": email}},
            status_code=400,
        )
    db.add(User(email=email, name=name, password_hash=hash_password(password), role="member", status="pending"))
    db.commit()
    return templates.TemplateResponse(request, "auth/registered.html", {"name": name})


@router.post("/account/password", dependencies=[Depends(verify_csrf)])
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_repeat: str = Form(...),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not verify_password(user.password_hash, current_password):
        flash(request, "Das aktuelle Passwort ist falsch.", "error")
    elif len(new_password) < MIN_PASSWORD_LENGTH:
        flash(request, f"Das neue Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen haben.", "error")
    elif new_password != new_password_repeat:
        flash(request, "Die neuen Passwörter stimmen nicht überein.", "error")
    else:
        user.password_hash = hash_password(new_password)
        db.commit()
        flash(request, "Passwort geändert.")
    return RedirectResponse("/settings", status_code=303)
