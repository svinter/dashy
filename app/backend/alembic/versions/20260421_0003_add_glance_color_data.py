"""Add color_data column to glance_entries and glance_trips.

Revision ID: 20260421_0003
Revises: 20260421_0002
Create Date: 2026-04-21 00:03:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260421_0003"
down_revision: Union[str, None] = "20260421_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE glance_entries ADD COLUMN color_data TEXT")
    op.execute("ALTER TABLE glance_trips ADD COLUMN color_data TEXT")


def downgrade() -> None:
    pass  # SQLite does not support DROP COLUMN
