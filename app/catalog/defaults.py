"""Standard-Katalog, der jedem neuen Gastgeber beim Freischalten angelegt wird."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import NON_VEGETARIAN_CATEGORIES, Ingredient, Product, ProductOption
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


# (Name, Symbol, Beschreibung, Art, bei allen Pizzen)
DEFAULT_OPTIONS: list[tuple[str, str, str, str, bool]] = [
    ("Calzone", "🥟", "Zusammengeklappt gebacken – Belag innen", "shape", True),
]

# Gerichte fuer die anderen Gaenge: Speisen-Art -> [(Name, Symbol, Auswahl Pflicht)]
DEFAULT_DISHES: dict[str, list[tuple[str, str, bool]]] = {
    "starter": [("Kürbiscremesuppe", "🎃", False)],
    "dessert": [("Eispalatschinke", "🥞", True)],
}

# Optionen dazu, jeweils nur beim genannten Gericht:
# Speisen-Art -> [(Name, Symbol, Art, Gericht)]
DEFAULT_DISH_OPTIONS: dict[str, list[tuple[str, str, str, str]]] = {
    "dessert": [
        ("Vanilleeis", "🍦", "shape", "Eispalatschinke"),
        ("Erdbeereis", "🍓", "shape", "Eispalatschinke"),
        ("mit Schokosauce", "🍫", "extra", "Eispalatschinke"),
    ],
}


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
            vegetarian=category not in NON_VEGETARIAN_CATEGORIES,
        ))
        added += 1
    db.flush()
    return added


def _has_any(db: Session, model, owner_id: int, kind: str) -> bool:
    return db.scalar(select(model.id).where(model.owner_id == owner_id, model.kind == kind).limit(1)) is not None


def seed_catalog(db: Session, owner_id: int) -> None:
    """Idempotent: legt Einstellungen, Zutaten, Gerichte und Optionen je
    Speisen-Art nur an, wenn der Gastgeber dort noch keine hat."""
    ensure_host_settings(db, owner_id)
    has_ingredients = db.scalar(select(Ingredient.id).where(Ingredient.owner_id == owner_id).limit(1))
    if has_ingredients is None:
        add_missing_default_ingredients(db, owner_id)

    if not _has_any(db, Product, owner_id, "pizza"):
        by_name = {
            i.name: i for i in db.scalars(select(Ingredient).where(Ingredient.owner_id == owner_id))
        }
        for index, (name, icon, description, ingredient_names) in enumerate(DEFAULT_PIZZAS):
            db.add(Product(
                owner_id=owner_id, kind="pizza", name=name, icon=icon, description=description,
                active=True, sort_order=index * 10,
                ingredients=[by_name[n] for n in ingredient_names if n in by_name],
            ))

    if not _has_any(db, ProductOption, owner_id, "pizza"):
        for index, (name, icon, description, group, all_products) in enumerate(DEFAULT_OPTIONS):
            db.add(ProductOption(
                owner_id=owner_id, kind="pizza", name=name, icon=icon, description=description,
                option_group=group, active=True, all_products=all_products, sort_order=(index + 1) * 10,
            ))

    for kind, dishes in DEFAULT_DISHES.items():
        if not _has_any(db, Product, owner_id, kind):
            for index, (name, icon, choice_required) in enumerate(dishes):
                db.add(Product(
                    owner_id=owner_id, kind=kind, name=name, icon=icon, description="",
                    active=True, choice_required=choice_required, sort_order=(index + 1) * 10,
                ))
    db.flush()

    for kind, options in DEFAULT_DISH_OPTIONS.items():
        if _has_any(db, ProductOption, owner_id, kind):
            continue
        by_name = {p.name: p for p in db.scalars(
            select(Product).where(Product.owner_id == owner_id, Product.kind == kind)
        )}
        for index, (name, icon, group, dish) in enumerate(options):
            db.add(ProductOption(
                owner_id=owner_id, kind=kind, name=name, icon=icon, description="", option_group=group,
                active=True, all_products=False, sort_order=(index + 1) * 10,
                products=[by_name[dish]] if dish in by_name else [],
            ))
    db.flush()
