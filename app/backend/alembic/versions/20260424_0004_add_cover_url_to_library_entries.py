"""Add cover_url to library_entries

Revision ID: 20260424_0004
Revises: 20260423_0005
Create Date: 2026-04-24
"""

from alembic import op

revision = "20260424_0004"
down_revision = "20260423_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE library_entries ADD COLUMN cover_url TEXT"
    )


def downgrade() -> None:
    pass  # SQLite doesn't support DROP COLUMN cleanly; no-op
