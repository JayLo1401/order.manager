from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.admin.routes import router as admin_router
from app.api.routes import router as api_router
from app.auth.dependencies import require_login
from app.auth.routes import router as auth_router
from app.catalog.routes import router as catalog_router
from app.config import settings
from app.database import get_db
from app.events.routes import router as events_router
from app.events.service import guest_url, today_event
from app.guest.routes import router as guest_router
from app.kitchen.routes import router as kitchen_router
from app.logging_config import configure_logging
from app.models.event import Order
from app.models.user import User
from app.settings_page.routes import router as settings_router
from app.templating import templates

configure_logging()

app = FastAPI(title="Bestell-Manager", docs_url=None, redoc_url=None, openapi_url=None)

static_dir = Path(__file__).parent / "static"

# Auf der Gaeste-Domain (z.B. pizza.jaycloud.at) sind nur die Gaeste-Seiten
# erreichbar; alles andere wird auf die Verwaltungs-Domain umgeleitet.
GUEST_HOST_ALLOWED_PREFIXES = ("/o/", "/static/")
GUEST_HOST_ALLOWED_PATHS = ("/sw.js", "/healthz", "/favicon.ico")


@app.middleware("http")
async def guest_host_guard(request: Request, call_next):
    guest_host = settings.guest_host
    host = request.headers.get("host", "").split(":")[0].lower()
    if guest_host and host == guest_host and guest_host != settings.admin_host:
        path = request.url.path
        if path == "/":
            return templates.TemplateResponse(request, "guest/landing.html", {})
        if not (path.startswith(GUEST_HOST_ALLOWED_PREFIXES) or path in GUEST_HOST_ALLOWED_PATHS):
            if settings.admin_base_url:
                return RedirectResponse(settings.admin_base_url.rstrip("/") + path, status_code=302)
            return templates.TemplateResponse(request, "guest/landing.html", {}, status_code=404)
    return await call_next(request)


# Nach guest_host_guard registriert => liegt aussen und ist auch dort aktiv.
# Lange Laufzeit, damit das Kuechen-Tablet angemeldet bleibt.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=settings.session_cookie_secure,
    max_age=60 * 60 * 24 * 60,
)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/sw.js")
def service_worker():
    # Eigene Route statt ueber /static, damit der Service Worker Scope "/" bekommt.
    return FileResponse(
        static_dir / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"}
    )


@app.get("/favicon.ico")
def favicon():
    return FileResponse(static_dir / "img" / "icon-192.png", media_type="image/png")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.exception_handler(HTTPException)
async def redirect_aware_exception_handler(request: Request, exc: HTTPException):
    # require_login()/require_guest() nutzen eine 303-HTTPException mit
    # Location-Header, um auf eine HTML-Seite umzuleiten.
    if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(url=exc.headers["Location"], status_code=303)
    if exc.status_code == 410 and request.url.path.startswith("/o/"):
        if request.url.path.endswith(("/api/status", "/push")):
            return await http_exception_handler(request, exc)
        return templates.TemplateResponse(request, "guest/expired.html", {}, status_code=410)
    return await http_exception_handler(request, exc)


@app.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    event = today_event(db, user)
    counts = {}
    if event is not None:
        counts = dict(db.execute(
            select(Order.status, func.count(Order.id)).where(Order.event_id == event.id).group_by(Order.status)
        ).all())
    pending_users = 0
    if user.is_superuser:
        pending_users = db.scalar(select(func.count(User.id)).where(User.status == "pending")) or 0
    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "event": event,
        "url": guest_url(request, event) if event else None,
        "counts": counts,
        "pending_users": pending_users,
    })


app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(catalog_router)
app.include_router(events_router)
app.include_router(settings_router)
app.include_router(kitchen_router)
app.include_router(guest_router)
app.include_router(api_router)
