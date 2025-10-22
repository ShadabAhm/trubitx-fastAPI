"""add recurring campaign fields

Revision ID: a1b2c3d4e5f6
Revises: ee2b4bb900e8
Create Date: 2025-10-18 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'ee2b4bb900e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add recurring campaign fields to campaigns table
    op.add_column('campaigns', sa.Column('is_recurring', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('campaigns', sa.Column('interval_hours', sa.Integer(), nullable=True))
    op.add_column('campaigns', sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('campaigns', sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Remove recurring campaign fields
    op.drop_column('campaigns', 'next_run_at')
    op.drop_column('campaigns', 'last_run_at')
    op.drop_column('campaigns', 'interval_hours')
    op.drop_column('campaigns', 'is_recurring')
