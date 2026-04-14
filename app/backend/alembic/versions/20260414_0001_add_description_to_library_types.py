"""Add description column to library_types

Revision ID: 20260414_0001
Revises: 20260413_0004
Create Date: 2026-04-14 00:01:00

description stores a brief human-readable description of the type (e.g.
"Full-length non-fiction books"). Displayed and editable on the Types page.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260414_0001"
down_revision: Union[str, None] = "20260413_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE library_types ADD COLUMN description TEXT")


def downgrade() -> None:
    # SQLite cannot drop columns; no-op.
    pass
