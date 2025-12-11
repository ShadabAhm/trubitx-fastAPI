"""add soft delete fields and status index to campaigns

Revision ID: c2d3e4f5a6b7
Revises: 88c00de0d9e3
Create Date: 2025-12-04 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = '88c00de0d9e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add soft delete fields to campaigns table
    op.add_column('campaigns', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('campaigns', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))

    # Add indexes for better query performance
    op.create_index('ix_campaigns_status', 'campaigns', ['status'])
    op.create_index('ix_campaigns_is_deleted', 'campaigns', ['is_deleted'])


def downgrade() -> None:
    # Remove indexes
    op.drop_index('ix_campaigns_is_deleted', table_name='campaigns')
    op.drop_index('ix_campaigns_status', table_name='campaigns')

    # Remove soft delete fields
    op.drop_column('campaigns', 'deleted_at')
    op.drop_column('campaigns', 'is_deleted')
