"""Add reading-list fields to library_books.

Revision ID: 20260426_0001
Revises: 20260425_0002
Create Date: 2026-04-26

New columns:
  date_finished     TEXT  — ISO date when book was finished (e.g. '2024-03-15')
  owned_format      TEXT  — 'kindle', 'audible', 'libro', or NULL
  reading_priority  INT   — 1=high, 2=medium, 3=normal; NULL = unset
  reading_notes     TEXT  — personal notes / comments about the book
  genre             TEXT  — 'fiction', 'nonfiction', 'coaching', or NULL
  date_added        TEXT  — ISO datetime when the row was added/imported

Status migration: NULL or empty status → 'unread' (backfills any pre-status rows).
"""

from alembic import op
import sqlalchemy as sa

revision = "20260426_0001"
down_revision = "20260425_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(library_books)"))]

    if "date_finished" not in existing:
        op.execute("ALTER TABLE library_books ADD COLUMN date_finished TEXT")
    if "owned_format" not in existing:
        op.execute("ALTER TABLE library_books ADD COLUMN owned_format TEXT")
    if "reading_priority" not in existing:
        op.execute("ALTER TABLE library_books ADD COLUMN reading_priority INTEGER")
    if "reading_notes" not in existing:
        op.execute("ALTER TABLE library_books ADD COLUMN reading_notes TEXT")
    if "genre" not in existing:
        op.execute("ALTER TABLE library_books ADD COLUMN genre TEXT")
    if "date_added" not in existing:
        op.execute("ALTER TABLE library_books ADD COLUMN date_added TEXT")

    # Backfill any rows where status slipped through as NULL or empty string.
    op.execute("UPDATE library_books SET status = 'unread' WHERE status IS NULL OR status = ''")


def downgrade() -> None:
    pass  # SQLite does not support DROP COLUMN
