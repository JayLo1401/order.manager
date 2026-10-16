"""Einrichtungs-Dialog im Kuechenmonitor (events.setup_done)

Revision ID: c6e8a0b2d4f6
Revises: b5d7f9a1c3e5
Create Date: 2026-10-16 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6e8a0b2d4f6'
down_revision: Union[str, None] = 'b5d7f9a1c3e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Bestehende Bestelltage gelten als eingerichtet - neue fragen einmal nach
    op.add_column('events', sa.Column('setup_done', sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('events') as batch:
        batch.drop_column('setup_done')
