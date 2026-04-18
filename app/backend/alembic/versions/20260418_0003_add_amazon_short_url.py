"""Add amazon_short_url to library_entries.

Revision ID: 20260418_0003
Revises: 20260418_0002
"""

from alembic import op

revision = "20260418_0003"
down_revision = "20260418_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE library_entries ADD COLUMN amazon_short_url TEXT"
    )


def downgrade() -> None:
    pass  # SQLite doesn't support DROP COLUMN in older versions
