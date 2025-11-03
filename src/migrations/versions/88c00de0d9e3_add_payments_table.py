"""add payments table

Revision ID: 88c00de0d9e3
Revises: 206de0a565a3
Create Date: 2025-10-30 15:29:35.530325

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '88c00de0d9e3'
down_revision: Union[str, None] = '206de0a565a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
