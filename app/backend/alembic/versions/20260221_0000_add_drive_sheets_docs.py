"""Add Drive files, Google Sheets, Google Docs tables with FTS and cache

Revision ID: 20260221_0000
Revises: 20250221_0001
Create Date: 2026-02-21 00:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260221_0000"
down_revision: Union[str, None] = "20250221_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS drive_files (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        web_view_link TEXT,
        icon_link TEXT,
        created_time TEXT,
        modified_time TEXT,
        modified_by_email TEXT,
        modified_by_name TEXT,
        owner_email TEXT,
        owner_name TEXT,
        shared INTEGER DEFAULT 0,
        starred INTEGER DEFAULT 0,
        trashed INTEGER DEFAULT 0,
        parent_id TEXT,
        parent_name TEXT,
        size_bytes INTEGER DEFAULT 0,
        description TEXT,
        content_preview TEXT,
        thumbnail_link TEXT,
        synced_at TEXT DEFAULT (datetime('now'))
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS google_sheets (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        web_view_link TEXT,
        owner_email TEXT,
        owner_name TEXT,
        modified_time TEXT,
        sheet_tabs_json TEXT,
        locale TEXT,
        time_zone TEXT,
        synced_at TEXT DEFAULT (datetime('now'))
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS google_docs (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        web_view_link TEXT,
        owner_email TEXT,
        owner_name TEXT,
        modified_time TEXT,
        content_preview TEXT,
        word_count INTEGER DEFAULT 0,
        synced_at TEXT DEFAULT (datetime('now'))
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS cached_drive_priorities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_json TEXT NOT NULL,
        generated_at TEXT DEFAULT (datetime('now'))
    )
    """)

    # FTS indexes
    op.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_drive_files USING fts5(
        name, description, content_preview,
        content='drive_files',
        content_rowid='rowid'
    )
    """)

    op.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_google_sheets USING fts5(
        title, sheet_tabs_json,
        content='google_sheets',
        content_rowid='rowid'
    )
    """)

    op.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_google_docs USING fts5(
        title, content_preview,
        content='google_docs',
        content_rowid='rowid'
    )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fts_google_docs")
    op.execute("DROP TABLE IF EXISTS fts_google_sheets")
    op.execute("DROP TABLE IF EXISTS fts_drive_files")
    op.execute("DROP TABLE IF EXISTS cached_drive_priorities")
    op.execute("DROP TABLE IF EXISTS google_docs")
    op.execute("DROP TABLE IF EXISTS google_sheets")
    op.execute("DROP TABLE IF EXISTS drive_files")
