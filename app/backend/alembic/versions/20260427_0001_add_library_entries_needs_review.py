"""Add needs_review, ingest_source, ingest_original to library_entries.

Revision ID: 20260427_0001
Revises: 20260426_0001
Create Date: 2026-04-27

New columns:
  needs_review    BOOLEAN  — 1 = entry is in inbox, awaiting type classification
  ingest_source   TEXT     — 'file' or 'url'
  ingest_original TEXT     — original filename or URL that was ingested
"""

from alembic import op
import sqlalchemy as sa

revision = "20260427_0001"
down_revision = "20260426_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(library_entries)"))]

    if "needs_review" not in existing:
        op.execute("ALTER TABLE library_entries ADD COLUMN needs_review BOOLEAN NOT NULL DEFAULT 0")
    if "ingest_source" not in existing:
        op.execute("ALTER TABLE library_entries ADD COLUMN ingest_source TEXT")
    if "ingest_original" not in existing:
        op.execute("ALTER TABLE library_entries ADD COLUMN ingest_original TEXT")


def downgrade() -> None:
    pass  # SQLite does not support DROP COLUMN
