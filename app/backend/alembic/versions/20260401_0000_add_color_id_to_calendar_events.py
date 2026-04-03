"""Add color_id column to calendar_events

Revision ID: 20260401_0000
Revises: 20260323_0000
Create Date: 2026-04-01 00:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260401_0000"
down_revision: Union[str, None] = "20260323_0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE calendar_events ADD COLUMN color_id TEXT")


def downgrade() -> None:
    # SQLite doesn't support DROP COLUMN; leave the column in place
    pass
