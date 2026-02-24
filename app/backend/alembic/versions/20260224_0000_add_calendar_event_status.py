"""Add status column to calendar_events for cancelled/declined tracking

Revision ID: 20260224_0000
Revises: 20260223_0000
Create Date: 2026-02-24 12:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260224_0000"
down_revision: Union[str, None] = "20260223_0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE calendar_events ADD COLUMN status TEXT DEFAULT 'confirmed'")
    op.execute("ALTER TABLE calendar_events ADD COLUMN self_response TEXT DEFAULT ''")


def downgrade() -> None:
    # SQLite doesn't support DROP COLUMN in older versions, but this is fine for our use
    pass
