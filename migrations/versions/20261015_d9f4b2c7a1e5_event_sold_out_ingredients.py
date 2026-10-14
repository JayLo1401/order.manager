"""event sold out ingredients

Revision ID: d9f4b2c7a1e5
Revises: 3c3a8bb54f16
Create Date: 2026-10-15 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9f4b2c7a1e5'
down_revision: Union[str, None] = '3c3a8bb54f16'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('events', sa.Column('sold_out_ingredient_ids', sa.JSON(), server_default='[]', nullable=False))


def downgrade() -> None:
    op.drop_column('events', 'sold_out_ingredient_ids')
