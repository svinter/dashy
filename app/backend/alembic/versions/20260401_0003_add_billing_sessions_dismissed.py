"""Add dismissed column to billing_sessions

Revision ID: 20260401_0003
Revises: 20260401_0002
Create Date: 2026-04-01 00:03:00

Dismissed sessions are events that have been explicitly skipped from the
unprocessed queue (e.g. non-coaching grape events like "Monthly To Do's").
They still occupy a calendar_event_id slot so they never reappear in the queue.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260401_0003"
down_revision: Union[str, None] = "20260401_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE billing_sessions ADD COLUMN dismissed BOOLEAN NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    pass  # SQLite can't drop columns
