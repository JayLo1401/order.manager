"""Bestell-Limit je Gang (Vorspeise / Hauptspeise / Nachspeise) statt global

Revision ID: a4c6e8f0b2d4
Revises: f1b3d5e7a9c2
Create Date: 2026-10-16 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4c6e8f0b2d4'
down_revision: Union[str, None] = 'f1b3d5e7a9c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

host_settings = sa.table(
    'host_settings', sa.column('id', sa.Integer), sa.column('max_orders_per_guest', sa.Integer),
    sa.column('max_orders_by_course', sa.JSON),
)


def upgrade() -> None:
    conn = op.get_bind()
    op.add_column('host_settings', sa.Column(
        'max_orders_by_course', sa.JSON(), server_default='{"starter": 1, "main": 1, "dessert": 1}', nullable=False,
    ))
    # Bisheriges globales Limit gilt fuer jeden Gang
    for row_id, limit in conn.execute(sa.select(host_settings.c.id, host_settings.c.max_orders_per_guest)).all():
        conn.execute(host_settings.update().where(host_settings.c.id == row_id).values(
            max_orders_by_course={"starter": limit, "main": limit, "dessert": limit},
        ))
    with op.batch_alter_table('host_settings') as batch:
        batch.drop_column('max_orders_per_guest')


def downgrade() -> None:
    conn = op.get_bind()
    op.add_column('host_settings', sa.Column('max_orders_per_guest', sa.Integer(), server_default='1', nullable=False))
    for row_id, limits in conn.execute(sa.select(host_settings.c.id, host_settings.c.max_orders_by_course)).all():
        conn.execute(host_settings.update().where(host_settings.c.id == row_id).values(
            max_orders_per_guest=int((limits or {}).get("main", 1)),
        ))
    with op.batch_alter_table('host_settings') as batch:
        batch.drop_column('max_orders_by_course')
