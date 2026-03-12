"""Add memory_entries and memory_summary tables for persistent memory system

Revision ID: 20260311_0000
Revises: 20260310_0001
Create Date: 2026-03-11 00:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260311_0000"
down_revision: Union[str, None] = "20260310_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS memory_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trigger TEXT NOT NULL DEFAULT 'sync',
        summary TEXT NOT NULL DEFAULT '',
        raw_context_json TEXT DEFAULT '',
        claude_session_id INTEGER,
        sources_json TEXT DEFAULT '[]',
        word_count INTEGER DEFAULT 0,
        data_hash TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (claude_session_id) REFERENCES claude_sessions(id) ON DELETE SET NULL
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS memory_summary (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        summary_text TEXT NOT NULL DEFAULT '',
        last_entry_id INTEGER DEFAULT 0,
        entry_count INTEGER DEFAULT 0,
        data_hash TEXT DEFAULT '',
        generated_at TEXT DEFAULT (datetime('now'))
    )
    """)

    op.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_memory USING fts5(
        summary,
        content='memory_entries',
        content_rowid='id'
    )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fts_memory")
    op.execute("DROP TABLE IF EXISTS memory_summary")
    op.execute("DROP TABLE IF EXISTS memory_entries")
