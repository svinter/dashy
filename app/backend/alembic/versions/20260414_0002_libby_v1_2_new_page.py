"""Libby v1.2 — needs_enrichment, enrichment log, all 16 type tables + registry entries

Revision ID: 20260414_0002
Revises: 20260414_0001
"""
from typing import Union
from alembic import op

revision: str = "20260414_0002"
down_revision: Union[str, None] = "20260414_0001"
branch_labels: Union[str, tuple, None] = None
depends_on: Union[str, tuple, None] = None


def upgrade() -> None:
    # 1 — needs_enrichment flag on library_entries
    op.execute(
        "ALTER TABLE library_entries ADD COLUMN needs_enrichment INTEGER NOT NULL DEFAULT 0"
    )

    # 2 — enrichment log table
    op.execute("""
        CREATE TABLE IF NOT EXISTS libby_enrichment_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id    INTEGER NOT NULL REFERENCES library_entries(id),
            task        TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            error       TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now'))
        )
    """)

    # 3 — Minimal entity tables for the 11 new types
    for tbl in [
        "library_essays",
        "library_videos",
        "library_movies",
        "library_worksheets",
        "library_assessments",
        "library_notes",
        "library_documents",
        "library_frameworks",
        "library_courses",
        "library_research",
        "library_quotes",
    ]:
        op.execute(f"CREATE TABLE IF NOT EXISTS {tbl} (id INTEGER PRIMARY KEY AUTOINCREMENT)")

    # 4 — Register all 11 missing types in library_types
    new_types = [
        ("e", "Essay",      "library_essays"),
        ("v", "Video",      "library_videos"),
        ("m", "Movie",      "library_movies"),
        ("s", "Worksheet",  "library_worksheets"),
        ("z", "Assessment", "library_assessments"),
        ("n", "Note",       "library_notes"),
        ("d", "Document",   "library_documents"),
        ("f", "Framework",  "library_frameworks"),
        ("c", "Course",     "library_courses"),
        ("r", "Research",   "library_research"),
        ("q", "Quote",      "library_quotes"),
    ]
    for code, name, table_name in new_types:
        op.execute(
            f"INSERT OR IGNORE INTO library_types (code, name, table_name) "
            f"VALUES ('{code}', '{name}', '{table_name}')"
        )

    # 5 — Also add cover_url + google_books_id to library_books (needed for Item 2)
    for col in [
        "ALTER TABLE library_books ADD COLUMN cover_url TEXT",
        "ALTER TABLE library_books ADD COLUMN google_books_id TEXT",
    ]:
        try:
            op.execute(col)
        except Exception:
            pass  # column already exists


def downgrade() -> None:
    pass
