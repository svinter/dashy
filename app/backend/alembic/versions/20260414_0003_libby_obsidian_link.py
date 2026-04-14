"""Add obsidian_link column to library_entries for vault home page tracking.

Revision ID: 20260414_0003
Revises: 20260414_0002
"""

from alembic import op

revision = "20260414_0003"
down_revision = "20260414_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Column may already exist if applied manually or via a prior session;
    # use IF NOT EXISTS workaround via raw sqlite3 pragma inspection.
    from alembic import op as _op
    import sqlalchemy as sa
    conn = _op.get_bind()
    cols = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(library_entries)"))]
    if "obsidian_link" not in cols:
        op.execute("ALTER TABLE library_entries ADD COLUMN obsidian_link TEXT")


def downgrade() -> None:
    pass  # SQLite does not support DROP COLUMN in older versions
