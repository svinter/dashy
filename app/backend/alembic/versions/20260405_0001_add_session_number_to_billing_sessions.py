"""Add session_number to billing_sessions

Revision ID: 20260405_0001
Revises: 20260404_0001
Create Date: 2026-04-05 00:01:00

Stores an explicit session number per client. When NULL the value is computed
at query time as ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY date, id).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260405_0001"
down_revision: Union[str, None] = "20260404_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE billing_sessions ADD COLUMN session_number INTEGER"
    )


def downgrade() -> None:
    pass  # SQLite can't drop columns
