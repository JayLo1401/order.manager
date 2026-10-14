"""Benutzerverwaltung fuer den Haupt-Admin (Freischalten neuer Registrierungen)."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_superuser, verify_csrf
from app.auth.routes import MIN_PASSWORD_LENGTH
from app.auth.security import hash_password
from app.catalog.defaults import seed_catalog
from app.database import get_db
from app.models.user import User
from app.templating import flash, templates
from app.timeutil import now_utc

router = APIRouter(prefix="/admin", dependencies=[Depends(require_superuser)])


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    return user


def _back() -> RedirectResponse:
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/users")
def users(request: Request, db: Session = Depends(get_db)):
    all_users = db.scalars(select(User).order_by(User.created_at)).all()
    return templates.TemplateResponse(request, "admin/users.html", {
        "pending": [u for u in all_users if u.status == "pending"],
        "users": [u for u in all_users if u.status != "pending"],
    })


@router.post("/users/{user_id}/approve", dependencies=[Depends(verify_csrf)])
def approve(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    user.status = "approved"
    user.approved_at = now_utc()
    seed_catalog(db, user.id)
    db.commit()
    flash(request, f"{user.name} wurde freigeschaltet.")
    return _back()


@router.post("/users/{user_id}/reject", dependencies=[Depends(verify_csrf)])
def reject(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    user.status = "rejected"
    db.commit()
    flash(request, f"Registrierung von {user.name} abgelehnt.")
    return _back()


@router.post("/users/{user_id}/status", dependencies=[Depends(verify_csrf)])
def set_status(
    request: Request,
    user_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_superuser),
):
    user = _get_user(db, user_id)
    if status not in ("approved", "disabled"):
        raise HTTPException(status_code=400)
    if user.id == admin.id:
        flash(request, "Du kannst dich nicht selbst deaktivieren.", "error")
        return _back()
    if status == "approved":
        seed_catalog(db, user.id)
        user.approved_at = user.approved_at or now_utc()
    user.status = status
    db.commit()
    flash(request, f"{user.name}: {'aktiviert' if status == 'approved' else 'deaktiviert'}.")
    return _back()


@router.post("/users/{user_id}/role", dependencies=[Depends(verify_csrf)])
def set_role(
    request: Request,
    user_id: int,
    role: str = Form(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_superuser),
):
    user = _get_user(db, user_id)
    if role not in ("member", "superuser"):
        raise HTTPException(status_code=400)
    if user.id == admin.id and role != "superuser":
        superusers = db.scalar(select(func.count(User.id)).where(User.role == "superuser"))
        if superusers <= 1:
            flash(request, "Der letzte Haupt-Admin kann nicht herabgestuft werden.", "error")
            return _back()
    user.role = role
    db.commit()
    flash(request, f"Rolle von {user.name} geändert.")
    return _back()


@router.post("/users/{user_id}/password", dependencies=[Depends(verify_csrf)])
def reset_password(request: Request, user_id: int, new_password: str = Form(...), db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    if len(new_password) < MIN_PASSWORD_LENGTH:
        flash(request, f"Das Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen haben.", "error")
        return _back()
    user.password_hash = hash_password(new_password)
    db.commit()
    flash(request, f"Passwort von {user.name} neu gesetzt.")
    return _back()


@router.post("/users/{user_id}/delete", dependencies=[Depends(verify_csrf)])
def delete(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_superuser),
):
    user = _get_user(db, user_id)
    if user.id == admin.id:
        flash(request, "Du kannst dich nicht selbst löschen.", "error")
        return _back()
    db.delete(user)
    db.commit()
    flash(request, f"{user.name} wurde gelöscht.")
    return _back()
