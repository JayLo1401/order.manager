"""Standard-Katalog, der jedem neuen Gastgeber beim Freischalten angelegt wird."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import Ingredient, Product
from app.models.settings import HostSettings

# (Name, Symbol, Kategorie, bei Wunschpizza vorausgewaehlt)
DEFAULT_INGREDIENTS: list[tuple[str, str, str, bool]] = [
    ("Tomatensauce", "🥫", "base", True),
    ("Crème fraîche", "🥛", "base", False),
    ("Pesto", "🌿", "base", False),
    ("Knoblauchöl", "🧄", "base", False),
    ("Mozzarella", "🧀", "cheese", True),
    ("Büffelmozzarella", "🐃", "cheese", False),
    ("Gorgonzola", "🧀", "cheese", False),
    ("Parmesan", "🧀", "cheese", False),
    ("Feta", "🧀", "cheese", False),
    ("Ziegenkäse", "🐐", "cheese", False),
    ("Schinken", "🍖", "meat", False),
    ("Salami", "🔴", "meat", False),
    ("Scharfe Salami", "🌶️", "meat", False),
    ("Speck", "🥓", "meat", False),
    ("Prosciutto crudo", "🥩", "meat", False),
    ("Hühnerfleisch", "🍗", "meat", False),
    ("Faschiertes", "🥩", "meat", False),
    ("Kebab", "🥙", "meat", False),
    ("Thunfisch", "🐟", "fish", False),
    ("Sardellen", "🐟", "fish", False),
    ("Garnelen", "🦐", "fish", False),
    ("Meeresfrüchte", "🦑", "fish", False),
    ("Champignons", "🍄", "vegetable", False),
    ("Paprika", "🫑", "vegetable", False),
    ("Zwiebeln", "🧅", "vegetable", False),
    ("Rote Zwiebeln", "🧅", "vegetable", False),
    ("Knoblauch", "🧄", "vegetable", False),
    ("Tomaten", "🍅", "vegetable", False),
    ("Cherrytomaten", "🍅", "vegetable", False),
    ("Oliven", "🫒", "vegetable", False),
    ("Mais", "🌽", "vegetable", False),
    ("Pfefferoni", "🌶️", "vegetable", False),
    ("Jalapeños", "🌶️", "vegetable", False),
    ("Artischocken", "🌼", "vegetable", False),
    ("Melanzani", "🍆", "vegetable", False),
    ("Zucchini", "🥒", "vegetable", False),
    ("Brokkoli", "🥦", "vegetable", False),
    ("Spinat", "🥬", "vegetable", False),
    ("Rucola", "🥬", "vegetable", False),
    ("Kapern", "🫛", "vegetable", False),
    ("Ananas", "🍍", "vegetable", False),
    ("Kartoffeln", "🥔", "vegetable", False),
    ("Ei", "🥚", "other", False),
    ("Oregano", "🌿", "herb", True),
    ("Basilikum", "🌱", "herb", False),
    ("Chiliflocken", "🔥", "herb", False),
]

# (Name, Symbol, Beschreibung, Zutaten)
DEFAULT_PIZZAS: list[tuple[str, str, str, list[str]]] = [
    ("Margherita", "🍕", "Der Klassiker", ["Tomatensauce", "Mozzarella", "Basilikum"]),
    ("Salami", "🍕", "", ["Tomatensauce", "Mozzarella", "Salami", "Oregano"]),
    ("Prosciutto", "🍖", "Schinken", ["Tomatensauce", "Mozzarella", "Schinken", "Oregano"]),
    ("Prosciutto e Funghi", "🍄", "Schinken & Champignons",
     ["Tomatensauce", "Mozzarella", "Schinken", "Champignons", "Oregano"]),
    ("Funghi", "🍄", "", ["Tomatensauce", "Mozzarella", "Champignons", "Oregano"]),
    ("Hawaii", "🍍", "", ["Tomatensauce", "Mozzarella", "Schinken", "Ananas"]),
    ("Tonno", "🐟", "", ["Tomatensauce", "Mozzarella", "Thunfisch", "Zwiebeln", "Oregano"]),
    ("Diavolo", "🌶️", "Scharf!", ["Tomatensauce", "Mozzarella", "Scharfe Salami", "Pfefferoni", "Chiliflocken"]),
    ("Quattro Formaggi", "🧀", "Vier Käse",
     ["Tomatensauce", "Mozzarella", "Gorgonzola", "Parmesan", "Ziegenkäse"]),
    ("Capricciosa", "🍕", "",
     ["Tomatensauce", "Mozzarella", "Schinken", "Champignons", "Artischocken", "Oliven"]),
    ("Vegetaria", "🥦", "Gemüse der Saison",
     ["Tomatensauce", "Mozzarella", "Paprika", "Melanzani", "Zucchini", "Champignons", "Zwiebeln"]),
    ("Bauernpizza", "🥓", "",
     ["Tomatensauce", "Mozzarella", "Speck", "Zwiebeln", "Kartoffeln", "Ei"]),
]


def ensure_host_settings(db: Session, owner_id: int) -> HostSettings:
    host_settings = db.scalar(select(HostSettings).where(HostSettings.owner_id == owner_id))
    if host_settings is None:
        host_settings = HostSettings(owner_id=owner_id)
        db.add(host_settings)
        db.flush()
    return host_settings


def add_missing_default_ingredients(db: Session, owner_id: int) -> int:
    """Legt fehlende Standard-Zutaten an (Abgleich ueber den Namen). Gibt die
    Anzahl neu angelegter Zutaten zurueck."""
    existing = {
        name.lower()
        for name in db.scalars(select(Ingredient.name).where(Ingredient.owner_id == owner_id))
    }
    added = 0
    for index, (name, icon, category, default_selected) in enumerate(DEFAULT_INGREDIENTS):
        if name.lower() in existing:
            continue
        db.add(Ingredient(
            owner_id=owner_id, kind="pizza", name=name, icon=icon, category=category,
            active=True, default_selected=default_selected, sort_order=index * 10,
        ))
        added += 1
    db.flush()
    return added


def seed_catalog(db: Session, owner_id: int) -> None:
    """Idempotent: legt Einstellungen, Zutaten und Pizzen nur an, wenn der
    Gastgeber noch keine hat."""
    ensure_host_settings(db, owner_id)
    has_ingredients = db.scalar(select(Ingredient.id).where(Ingredient.owner_id == owner_id).limit(1))
    if has_ingredients is None:
        add_missing_default_ingredients(db, owner_id)

    has_products = db.scalar(select(Product.id).where(Product.owner_id == owner_id).limit(1))
    if has_products is None:
        by_name = {
            i.name: i for i in db.scalars(select(Ingredient).where(Ingredient.owner_id == owner_id))
        }
        for index, (name, icon, description, ingredient_names) in enumerate(DEFAULT_PIZZAS):
            db.add(Product(
                owner_id=owner_id, kind="pizza", name=name, icon=icon, description=description,
                active=True, sort_order=index * 10,
                ingredients=[by_name[n] for n in ingredient_names if n in by_name],
            ))
    db.flush()
