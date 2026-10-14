from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.timeutil import now_utc

ORDER_STATUSES = {
    "new": "Eingegangen",
    "in_progress": "In Zubereitung",
    "done": "Fertig",
    "cancelled": "Storniert",
}


class Event(Base):
    """Ein Bestelltag: der Link/QR-Code fuer die Gaeste ist genau an `day` gueltig."""

    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("owner_id", "kind", "day", name="uq_events_owner_kind_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="pizza")
    day: Mapped[date] = mapped_column(Date)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(120), default="")
    ordering_open: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    orders: Mapped[list["Order"]] = relationship(back_populates="event", cascade="all, delete-orphan")


class Guest(Base):
    __tablename__ = "guests"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    table_no: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    @property
    def label(self) -> str:
        parts = [self.name]
        if self.table_no:
            parts.append(f"Tisch {self.table_no}")
        return " · ".join(p for p in parts if p)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    # Momentaufnahme zum Bestellzeitpunkt, damit spaetere Aenderungen an Pizzen/
    # Zutaten bestehende Bestellungen nicht veraendern: [{"name": ..., "icon": ...}]
    item_name: Mapped[str] = mapped_column(String(120))
    item_icon: Mapped[str] = mapped_column(String(16), default="")
    ingredients: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    event: Mapped[Event] = relationship(back_populates="orders")
    guest: Mapped[Guest] = relationship()

    @property
    def status_label(self) -> str:
        return ORDER_STATUSES.get(self.status, self.status)
