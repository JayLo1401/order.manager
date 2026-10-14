"""guest extra orders

Revision ID: c3d8a5f1e2b4
Revises: b7e2c41a9f03
Create Date: 2026-10-15 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d8a5f1e2b4'
down_revision: Union[str, None] = 'b7e2c41a9f03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('guests', sa.Column('extra_orders', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('guests', 'extra_orders')
