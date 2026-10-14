from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Bestell-Bereiche. Aktuell nur Pizza; Grill & Co. kommen spaeter als weitere
# Werte dazu (Zutaten, Produkte und Bestelltage sind bereits danach getrennt).
KINDS = {"pizza": "Pizza"}

INGREDIENT_CATEGORIES = {
    "base": "Basis & Saucen",
    "cheese": "Käse",
    "meat": "Fleisch & Wurst",
    "fish": "Fisch & Meeresfrüchte",
    "vegetable": "Gemüse & Obst",
    "herb": "Kräuter & Gewürze",
    "other": "Sonstiges",
}

product_ingredients = Table(
    "product_ingredients",
    Base.metadata,
    Column("product_id", ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    Column("ingredient_id", ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True),
)


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="pizza")
    name: Mapped[str] = mapped_column(String(80))
    icon: Mapped[str] = mapped_column(String(16), default="")
    category: Mapped[str] = mapped_column(String(20), default="other")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bei der Wunschpizza bereits vorausgewaehlt (z.B. Tomatensauce, Mozzarella)
    default_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def category_label(self) -> str:
        return INGREDIENT_CATEGORIES.get(self.category, self.category)


class Product(Base):
    """Vorgefertigtes Gericht, z.B. Pizza Margherita."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="pizza")
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(16), default="🍕")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    ingredients: Mapped[list[Ingredient]] = relationship(
        secondary=product_ingredients, order_by=(Ingredient.sort_order, Ingredient.name)
    )

    @property
    def available(self) -> bool:
        """Nur bestellbar, wenn alle Zutaten aktiv sind."""
        return self.active and all(i.active for i in self.ingredients)
