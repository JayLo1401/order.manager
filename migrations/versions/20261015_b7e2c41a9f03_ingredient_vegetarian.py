"""ingredient vegetarian flag

Revision ID: b7e2c41a9f03
Revises: 9dfd78fdce01
Create Date: 2026-10-15 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2c41a9f03'
down_revision: Union[str, None] = '9dfd78fdce01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ingredients', sa.Column('vegetarian', sa.Boolean(), server_default=sa.true(), nullable=False))
    # Bestehende Zutaten: Fleisch und Fisch sind nicht vegetarisch
    op.execute("UPDATE ingredients SET vegetarian = false WHERE category IN ('meat', 'fish')")


def downgrade() -> None:
    op.drop_column('ingredients', 'vegetarian')
