"""Add subtitle, categories, preview_link, authors to library_books.

Revision ID: 20260418_0002
Revises: 20260414_0003
"""

from alembic import op
import sqlalchemy as sa

revision = "20260418_0002"
down_revision = "20260414_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(library_books)"))]
    if "subtitle" not in cols:
        op.execute("ALTER TABLE library_books ADD COLUMN subtitle TEXT")
    if "categories" not in cols:
        op.execute("ALTER TABLE library_books ADD COLUMN categories TEXT")
    if "preview_link" not in cols:
        op.execute("ALTER TABLE library_books ADD COLUMN preview_link TEXT")
    if "authors" not in cols:
        op.execute("ALTER TABLE library_books ADD COLUMN authors TEXT")


def downgrade() -> None:
    pass  # SQLite does not support DROP COLUMN in older versions
