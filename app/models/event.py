from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.catalog import KINDS
from app.timeutil import now_utc

ORDER_STATUSES = {
    "new": "Eingegangen",
    "in_progress": "In Zubereitung",
    "done": "Fertig",
    "cancelled": "Storniert",
}

# Gaenge in ihrer Reihenfolge. Die Kueche schaltet sie nacheinander frei
# (Vorspeise -> geschlossen -> Hauptspeise -> geschlossen -> Nachspeise).
COURSES = {"starter": "Vorspeise", "main": "Hauptspeise", "dessert": "Nachspeise"}

# Was es als Hauptspeise gibt: Pizza (inkl. Wunschpizza) oder andere Hauptgerichte
MAIN_KINDS = ("pizza", "main")


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
    # Gaenge, die es an diesem Tag gibt (Reihenfolge wie in COURSES).
    # Beim Aendern immer eine neue Liste zuweisen.
    courses: Mapped[list] = mapped_column(JSON, default=lambda: ["main"], server_default='["main"]')
    main_kind: Mapped[str] = mapped_column(String(20), default="pizza", server_default="pizza")
    # Gang, der gerade bestellt werden kann; None = geschlossen
    current_course: Mapped[str | None] = mapped_column(String(20), default="main")
    # Zutaten, die heute ausgegangen sind (im Kuechenmonitor gesetzt). Haengt am
    # Bestelltag, damit am naechsten Tag automatisch wieder alles verfuegbar ist.
    # Beim Aendern immer eine neue Liste zuweisen (sonst erkennt SQLAlchemy es nicht).
    sold_out_ingredient_ids: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    orders: Mapped[list["Order"]] = relationship(back_populates="event", cascade="all, delete-orphan")

    @property
    def sold_out_ids(self) -> set[int]:
        return set(self.sold_out_ingredient_ids or [])

    @property
    def ordering_open(self) -> bool:
        return self.current_course is not None

    def kind_for(self, course: str) -> str:
        """Speisen-Art eines Gangs (Hauptspeise: Pizza oder andere Gerichte)."""
        return self.main_kind if course == "main" else course

    def course_label(self, course: str) -> str:
        return COURSES.get(course, course)

    def course_icon(self, course: str) -> str:
        return KINDS.get(self.kind_for(course), {}).get("icon", "🍽️")

    def course_noun(self, course: str) -> str:
        """Fuer Texte wie "Deine Pizza ist fertig" / "Deine Vorspeise ist fertig"."""
        return "Pizza" if self.kind_for(course) == "pizza" else self.course_label(course)

    def course_plural(self, course: str) -> str:
        """Pizzen, Vorspeisen, Hauptspeisen, Nachspeisen."""
        return "Pizzen" if self.kind_for(course) == "pizza" else f"{self.course_label(course)}n"


class Guest(Base):
    __tablename__ = "guests"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    table_no: Mapped[str] = mapped_column(String(20), default="")
    # Zusaetzlich zum Limit aus den Einstellungen freigegebene Bestellungen je
    # Gang ("Nachschlag", vergeben im Kuechenmonitor), z.B. {"main": 1}.
    # Beim Aendern immer ein neues dict zuweisen.
    extra_by_course: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    # Vom Gast angefragter Nachschlag je Gang: "pending" (Kueche entscheidet noch)
    # oder "declined" (abgelehnt). Bei Freigabe wird der Eintrag entfernt.
    # Beim Aendern immer ein neues dict zuweisen.
    extra_requests: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    def extra_for(self, course: str | None) -> int:
        return int((self.extra_by_course or {}).get(course, 0)) if course else 0

    def extra_request(self, course: str | None) -> str | None:
        return (self.extra_requests or {}).get(course) if course else None

    def set_extra_request(self, course: str, state: str | None) -> None:
        requests = dict(self.extra_requests or {})
        if state is None:
            requests.pop(course, None)
        else:
            requests[course] = state
        self.extra_requests = requests

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
    course: Mapped[str] = mapped_column(String(20), default="main", server_default="main")
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    # "Ich moechte keine Vorspeise/Nachspeise" - fuer die Kueche nur zur Info
    is_skip: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Momentaufnahme zum Bestellzeitpunkt, damit spaetere Aenderungen an Pizzen/
    # Zutaten bestehende Bestellungen nicht veraendern: [{"name": ..., "icon": ...}]
    item_name: Mapped[str] = mapped_column(String(120))
    item_icon: Mapped[str] = mapped_column(String(16), default="")
    # Bei abgeaenderten fertigen Pizzen tragen hinzugefuegte Zutaten "added": True
    ingredients: Mapped[list] = mapped_column(JSON, default=list)
    # Von einer fertigen Pizza weggelassene Zutaten ("ohne Zwiebel"): [{"name": ..., "icon": ...}]
    removed_ingredients: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # Gewaehlte Optionen (Momentaufnahme): [{"name": ..., "icon": ..., "group": ...}]
    options: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
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

    @property
    def vegetarian(self) -> bool:
        # Aeltere Bestellungen ohne "vegetarian" in der Momentaufnahme gelten
        # vorsichtshalber als nicht vegetarisch.
        items = self.ingredients or []
        return bool(items) and all(i.get("vegetarian", False) for i in items)
