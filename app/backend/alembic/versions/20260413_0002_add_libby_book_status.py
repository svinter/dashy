"""Add status to library_books

Revision ID: 20260413_0002
Revises: 20260413_0001
Create Date: 2026-04-13 00:02:00

status tracks reading progress for books: 'unread', 'reading', 'read'.
Defaults to 'unread' for existing rows.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260413_0002"
down_revision: Union[str, None] = "20260413_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE library_books ADD COLUMN status TEXT NOT NULL DEFAULT 'unread'"
    )


def downgrade() -> None:
    # SQLite cannot drop columns; no-op.
    pass
