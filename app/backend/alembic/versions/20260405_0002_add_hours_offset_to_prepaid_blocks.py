"""Add hours_offset to billing_prepaid_blocks

Revision ID: 20260405_0002
Revises: 20260405_0001
Create Date: 2026-04-05 00:02:00

Stores a manual starting-hour offset to account for pre-Dashy session history.
When set, the cumulative display in the Sessions view starts from this value
rather than 0 (e.g. hours_offset=5 means "5 hours already used before tracking began").
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260405_0002"
down_revision: Union[str, None] = "20260405_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE billing_prepaid_blocks ADD COLUMN hours_offset REAL NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    pass  # SQLite can't drop columns
