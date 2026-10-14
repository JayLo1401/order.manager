from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Table, Text, true
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

# Vorbelegung fuer "vegetarisch", wenn eine Zutat neu angelegt wird
NON_VEGETARIAN_CATEGORIES = ("meat", "fish")

# Arten von Optionen: aus "shape" darf der Gast hoechstens eine waehlen
# (Calzone UND Sternpizza ergibt keinen Sinn), "extra" ist frei kombinierbar.
OPTION_GROUPS = {
    "shape": "Form",
    "extra": "Extra",
}

product_ingredients = Table(
    "product_ingredients",
    Base.metadata,
    Column("product_id", ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    Column("ingredient_id", ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True),
)

# Manuelle Zuordnung von Optionen zu Pizzen (nur fuer Optionen mit all_products=False)
product_option_links = Table(
    "product_option_links",
    Base.metadata,
    Column("product_id", ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    Column("option_id", ForeignKey("product_options.id", ondelete="CASCADE"), primary_key=True),
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
    vegetarian: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def category_label(self) -> str:
        return INGREDIENT_CATEGORIES.get(self.category, self.category)


class ProductOption(Base):
    """Zubereitungs-Option, z.B. "als Calzone", "als Sternpizza", "mit Kaeserand"."""

    __tablename__ = "product_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="pizza")
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(16), default="")
    option_group: Mapped[str] = mapped_column(String(20), default="extra")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # True: bei allen Pizzen inkl. Wunschpizza waehlbar. False: nur bei den
    # zugeordneten Pizzen, bei der Wunschpizza nie.
    all_products: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    products: Mapped[list["Product"]] = relationship(
        secondary=product_option_links, back_populates="options"
    )

    @property
    def group_label(self) -> str:
        return OPTION_GROUPS.get(self.option_group, self.option_group)

    def available_for(self, product: "Product | None") -> bool:
        """product=None steht fuer die Wunschpizza."""
        if not self.active:
            return False
        if self.all_products:
            return True
        return product is not None and product in self.products


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
    options: Mapped[list[ProductOption]] = relationship(
        secondary=product_option_links, back_populates="products",
        order_by=(ProductOption.sort_order, ProductOption.name),
    )

    @property
    def available(self) -> bool:
        """Nur bestellbar, wenn alle Zutaten aktiv sind."""
        return self.active and all(i.active for i in self.ingredients)

    @property
    def vegetarian(self) -> bool:
        """Ergibt sich aus den Zutaten - kein eigenes Feld, damit es nie veraltet."""
        return bool(self.ingredients) and all(i.vegetarian for i in self.ingredients)
