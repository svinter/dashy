"""Add text_color column to glance_trips and glance_entries.

Revision ID: 20260422_0002
Revises: 20260422_0001
Create Date: 2026-04-22 00:02:00

Changes:
  - Add text_color (nullable text) to glance_trips
  - Add text_color (nullable text) to glance_entries
  - NULL means default black; allowed values: null, #FF0000, #0000FF, #FFFFFF
"""
from alembic import op
import sqlalchemy as sa

revision = '20260422_0002'
down_revision = '20260422_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('glance_trips', sa.Column('text_color', sa.Text(), nullable=True))
    op.add_column('glance_entries', sa.Column('text_color', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('glance_trips', 'text_color')
    op.drop_column('glance_entries', 'text_color')
