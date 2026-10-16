from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

DEFAULT_ORDER_LIMITS = {"starter": 1, "main": 1, "dessert": 1}

GUEST_IDENTITY_MODES = {
    "name": "Name",
    "table": "Tischnummer",
    "name_and_table": "Name und Tischnummer",
}


class HostSettings(Base):
    """Verwaltungs-Einstellungen eines Gastgebers (ein Datensatz pro Benutzer)."""

    __tablename__ = "host_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    event_title: Mapped[str] = mapped_column(String(120), default="Pizzaabend")
    welcome_text: Mapped[str] = mapped_column(Text, default="")
    guest_identity: Mapped[str] = mapped_column(String(20), default="name")
    # Bestellungen pro Gast je Gang, z.B. {"starter": 2, "main": 1, "dessert": 1}.
    # 0 = unbegrenzt, fehlender Gang = 1. Beim Aendern immer ein neues dict zuweisen.
    max_orders_by_course: Mapped[dict] = mapped_column(
        JSON, default=lambda: dict(DEFAULT_ORDER_LIMITS), server_default='{"starter": 1, "main": 1, "dessert": 1}'
    )
    allow_presets: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_custom: Mapped[bool] = mapped_column(Boolean, default=True)
    # 0 = unbegrenzt
    max_custom_ingredients: Mapped[int] = mapped_column(Integer, default=0)
    allow_note: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_cancel: Mapped[bool] = mapped_column(Boolean, default=True)

    def order_limit(self, course: str) -> int:
        """Max. Bestellungen pro Gast in diesem Gang (0 = unbegrenzt)."""
        return int((self.max_orders_by_course or {}).get(course, DEFAULT_ORDER_LIMITS.get(course, 1)))


class PlatformSettings(Base):
    """Singleton-Zeile (id=1) fuer server-weite Werte, z.B. die VAPID-Schluessel
    fuer Push-Benachrichtigungen (werden beim ersten Bedarf erzeugt)."""

    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    vapid_private_pem: Mapped[str] = mapped_column(Text, default="")
    vapid_public_key: Mapped[str] = mapped_column(String(200), default="")
