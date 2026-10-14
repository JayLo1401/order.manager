from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

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
    # 0 = unbegrenzt
    max_orders_per_guest: Mapped[int] = mapped_column(Integer, default=1)
    allow_presets: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_custom: Mapped[bool] = mapped_column(Boolean, default=True)
    # 0 = unbegrenzt
    max_custom_ingredients: Mapped[int] = mapped_column(Integer, default=0)
    allow_note: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_cancel: Mapped[bool] = mapped_column(Boolean, default=True)


class PlatformSettings(Base):
    """Singleton-Zeile (id=1) fuer server-weite Werte, z.B. die VAPID-Schluessel
    fuer Push-Benachrichtigungen (werden beim ersten Bedarf erzeugt)."""

    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    vapid_private_pem: Mapped[str] = mapped_column(Text, default="")
    vapid_public_key: Mapped[str] = mapped_column(String(200), default="")
