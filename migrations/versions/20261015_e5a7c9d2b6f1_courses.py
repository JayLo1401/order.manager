"""courses (Vorspeise / Hauptspeise / Nachspeise)

Revision ID: e5a7c9d2b6f1
Revises: d9f4b2c7a1e5
Create Date: 2026-10-15 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a7c9d2b6f1'
down_revision: Union[str, None] = 'd9f4b2c7a1e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Bewusst hier eingefroren (nicht aus app.catalog.defaults importiert), damit
# die Migration auch nach spaeteren Aenderungen am Standard-Katalog gleich bleibt.
DISHES = [
    ("starter", "Kürbiscremesuppe", "🎃", False),
    ("dessert", "Eispalatschinke", "🥞", True),
]
DISH_OPTIONS = [
    ("dessert", "Vanilleeis", "🍦", "shape", "Eispalatschinke"),
    ("dessert", "Erdbeereis", "🍓", "shape", "Eispalatschinke"),
    ("dessert", "mit Schokosauce", "🍫", "extra", "Eispalatschinke"),
]

events = sa.table(
    'events', sa.column('id', sa.Integer), sa.column('ordering_open', sa.Boolean),
    sa.column('current_course', sa.String),
)
guests = sa.table(
    'guests', sa.column('id', sa.Integer), sa.column('extra_orders', sa.Integer),
    sa.column('extra_by_course', sa.JSON),
)
host_settings = sa.table('host_settings', sa.column('owner_id', sa.Integer))
products = sa.table(
    'products', sa.column('id', sa.Integer), sa.column('owner_id', sa.Integer), sa.column('kind', sa.String),
    sa.column('name', sa.String), sa.column('description', sa.Text), sa.column('icon', sa.String),
    sa.column('active', sa.Boolean), sa.column('choice_required', sa.Boolean), sa.column('sort_order', sa.Integer),
)
product_options = sa.table(
    'product_options', sa.column('id', sa.Integer), sa.column('owner_id', sa.Integer),
    sa.column('kind', sa.String), sa.column('name', sa.String), sa.column('description', sa.Text),
    sa.column('icon', sa.String), sa.column('option_group', sa.String), sa.column('active', sa.Boolean),
    sa.column('all_products', sa.Boolean), sa.column('sort_order', sa.Integer),
)
product_option_links = sa.table(
    'product_option_links', sa.column('product_id', sa.Integer), sa.column('option_id', sa.Integer),
)


def _has(conn, table, owner_id, kind) -> bool:
    return conn.execute(
        sa.select(table.c.id).where(table.c.owner_id == owner_id, table.c.kind == kind).limit(1)
    ).first() is not None


def _seed_dishes(conn) -> None:
    """Bestehende Gastgeber bekommen die Standard-Gerichte fuer Vor- und
    Nachspeise einmalig - neue bekommen sie ueber seed_catalog()."""
    for owner_id in conn.execute(sa.select(host_settings.c.owner_id)).scalars().all():
        for index, (kind, name, icon, choice_required) in enumerate(DISHES):
            if _has(conn, products, owner_id, kind):
                continue
            conn.execute(products.insert().values(
                owner_id=owner_id, kind=kind, name=name, description="", icon=icon, active=True,
                choice_required=choice_required, sort_order=(index + 1) * 10,
            ))
        for kind in {o[0] for o in DISH_OPTIONS}:
            if _has(conn, product_options, owner_id, kind):
                continue
            for index, (option_kind, name, icon, group, dish) in enumerate(DISH_OPTIONS):
                if option_kind != kind:
                    continue
                option_id = conn.execute(product_options.insert().values(
                    owner_id=owner_id, kind=kind, name=name, description="", icon=icon, option_group=group,
                    active=True, all_products=False, sort_order=(index + 1) * 10,
                ).returning(product_options.c.id)).scalar_one()
                product_id = conn.execute(sa.select(products.c.id).where(
                    products.c.owner_id == owner_id, products.c.kind == kind, products.c.name == dish,
                ).limit(1)).scalar()
                if product_id is not None:
                    conn.execute(product_option_links.insert().values(product_id=product_id, option_id=option_id))


def upgrade() -> None:
    conn = op.get_bind()

    # Bestelltag: Gaenge statt "Bestellungen offen/pausiert"
    op.add_column('events', sa.Column('courses', sa.JSON(), server_default='["main"]', nullable=False))
    op.add_column('events', sa.Column('main_kind', sa.String(length=20), server_default='pizza', nullable=False))
    op.add_column('events', sa.Column('current_course', sa.String(length=20), nullable=True))
    conn.execute(events.update().where(events.c.ordering_open.is_(True)).values(current_course='main'))
    with op.batch_alter_table('events') as batch:
        batch.drop_column('ordering_open')

    # Nachschlag je Gang; bisherige Freigaben galten fuer die (einzige) Hauptspeise
    op.add_column('guests', sa.Column('extra_by_course', sa.JSON(), server_default='{}', nullable=False))
    for guest_id, extra in conn.execute(
        sa.select(guests.c.id, guests.c.extra_orders).where(guests.c.extra_orders > 0)
    ).all():
        conn.execute(guests.update().where(guests.c.id == guest_id).values(extra_by_course={"main": extra}))
    with op.batch_alter_table('guests') as batch:
        batch.drop_column('extra_orders')

    op.add_column('orders', sa.Column('course', sa.String(length=20), server_default='main', nullable=False))
    op.add_column('orders', sa.Column('is_skip', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('products', sa.Column('choice_required', sa.Boolean(), server_default=sa.false(), nullable=False))

    _seed_dishes(conn)


def downgrade() -> None:
    conn = op.get_bind()
    op.drop_column('products', 'choice_required')
    op.drop_column('orders', 'is_skip')
    op.drop_column('orders', 'course')

    op.add_column('guests', sa.Column('extra_orders', sa.Integer(), server_default='0', nullable=False))
    for guest_id, extra in conn.execute(sa.select(guests.c.id, guests.c.extra_by_course)).all():
        if extra and extra.get("main"):
            conn.execute(guests.update().where(guests.c.id == guest_id).values(extra_orders=int(extra["main"])))
    with op.batch_alter_table('guests') as batch:
        batch.drop_column('extra_by_course')

    op.add_column('events', sa.Column('ordering_open', sa.Boolean(), server_default=sa.true(), nullable=False))
    conn.execute(events.update().where(events.c.current_course.is_(None)).values(ordering_open=False))
    with op.batch_alter_table('events') as batch:
        batch.drop_column('current_course')
        batch.drop_column('main_kind')
        batch.drop_column('courses')
