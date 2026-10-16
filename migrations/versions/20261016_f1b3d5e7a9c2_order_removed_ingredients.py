"""order removed_ingredients (fertige Pizza abgeaendert: "ohne Zwiebel")

Revision ID: f1b3d5e7a9c2
Revises: e5a7c9d2b6f1
Create Date: 2026-10-16 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1b3d5e7a9c2'
down_revision: Union[str, None] = 'e5a7c9d2b6f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('removed_ingredients', sa.JSON(), server_default='[]', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('orders') as batch:
        batch.drop_column('removed_ingredients')
