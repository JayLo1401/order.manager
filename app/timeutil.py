from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.config import settings

LOCAL_TZ = ZoneInfo(settings.timezone)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_local() -> date:
    """Der "aktuelle Tag" fuer die Gueltigkeit der Bestell-Links (Ortszeit)."""
    return datetime.now(LOCAL_TZ).date()


def to_local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        # SQLite (Tests) liefert naive Werte zurueck - die sind UTC.
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TZ)
