from pathlib import Path

import jinja2
from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import get_csrf_token
from app.models.catalog import KINDS
from app.models.event import COURSES
from app.timeutil import to_local

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def flash(request: Request, message: str, category: str = "ok") -> None:
    messages = request.session.get("_flash", [])
    messages.append({"message": message, "category": category})
    request.session["_flash"] = messages


@jinja2.pass_context
def _get_flashed(context) -> list[dict]:
    request = context.get("request")
    return request.session.pop("_flash", []) if request else []


@jinja2.pass_context
def _csrf_token(context) -> str:
    return get_csrf_token(context["request"])


def _local_time(value, fmt: str = "%H:%M") -> str:
    local = to_local(value)
    return local.strftime(fmt) if local else ""


templates.env.globals["COURSES"] = COURSES
templates.env.globals["KINDS"] = KINDS
templates.env.globals["get_flashed"] = _get_flashed
templates.env.globals["csrf_token"] = _csrf_token
templates.env.filters["localtime"] = _local_time
