"""Rename employees to people, add contact fields, create person_links/attributes/connections

Revision ID: 20260222_0000
Revises: 20260221_0000
Create Date: 2026-02-22 00:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260222_0000"
down_revision: Union[str, None] = "20260221_0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Rename employees → people ──
    # SQLite 3.25+ automatically updates FK references in other tables
    op.execute("ALTER TABLE employees RENAME TO people")

    # ── 2. Add new columns to people ──
    op.execute("ALTER TABLE people ADD COLUMN is_coworker INTEGER DEFAULT 1")
    op.execute("ALTER TABLE people ADD COLUMN company TEXT")
    op.execute("ALTER TABLE people ADD COLUMN phone TEXT")
    op.execute("ALTER TABLE people ADD COLUMN bio TEXT")
    op.execute("ALTER TABLE people ADD COLUMN linkedin_url TEXT")
    op.execute("ALTER TABLE people ADD COLUMN source TEXT DEFAULT 'manual'")

    # All existing records are coworkers
    op.execute("UPDATE people SET is_coworker = 1 WHERE is_coworker IS NULL")

    # ── 3. Rename employee_id → person_id in direct FK tables ──
    op.execute("ALTER TABLE notes RENAME COLUMN employee_id TO person_id")
    op.execute("ALTER TABLE granola_meetings RENAME COLUMN employee_id TO person_id")
    op.execute("ALTER TABLE meeting_files RENAME COLUMN employee_id TO person_id")
    op.execute("ALTER TABLE one_on_one_notes RENAME COLUMN employee_id TO person_id")

    # ── 4. Rename junction tables and their columns ──
    op.execute("ALTER TABLE note_employees RENAME TO note_people")
    op.execute("ALTER TABLE note_people RENAME COLUMN employee_id TO person_id")

    op.execute("ALTER TABLE issue_employees RENAME TO issue_people")
    op.execute("ALTER TABLE issue_people RENAME COLUMN employee_id TO person_id")

    # ── 5. Recreate FTS table for people (can't rename virtual tables) ──
    op.execute("DROP TABLE IF EXISTS fts_employees")
    op.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_people USING fts5(
        name, title, company, bio, role_content,
        content='people',
        content_rowid='rowid'
    )
    """)
    op.execute("INSERT INTO fts_people(fts_people) VALUES('rebuild')")

    # ── 6. Create person_links table ──
    op.execute("""
    CREATE TABLE IF NOT EXISTS person_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id TEXT NOT NULL,
        link_type TEXT NOT NULL,
        url TEXT NOT NULL,
        label TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
    )
    """)

    # ── 7. Create person_attributes table ──
    op.execute("""
    CREATE TABLE IF NOT EXISTS person_attributes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE,
        UNIQUE(person_id, key)
    )
    """)

    # ── 8. Create person_connections table ──
    op.execute("""
    CREATE TABLE IF NOT EXISTS person_connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_a_id TEXT NOT NULL,
        person_b_id TEXT NOT NULL,
        relationship TEXT,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (person_a_id) REFERENCES people(id) ON DELETE CASCADE,
        FOREIGN KEY (person_b_id) REFERENCES people(id) ON DELETE CASCADE,
        UNIQUE(person_a_id, person_b_id)
    )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS person_connections")
    op.execute("DROP TABLE IF EXISTS person_attributes")
    op.execute("DROP TABLE IF EXISTS person_links")

    op.execute("DROP TABLE IF EXISTS fts_people")
    op.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_employees USING fts5(
        name, title, role_content,
        content='employees',
        content_rowid='rowid'
    )
    """)

    op.execute("ALTER TABLE issue_people RENAME COLUMN person_id TO employee_id")
    op.execute("ALTER TABLE issue_people RENAME TO issue_employees")

    op.execute("ALTER TABLE note_people RENAME COLUMN person_id TO employee_id")
    op.execute("ALTER TABLE note_people RENAME TO note_employees")

    op.execute("ALTER TABLE one_on_one_notes RENAME COLUMN person_id TO employee_id")
    op.execute("ALTER TABLE meeting_files RENAME COLUMN person_id TO employee_id")
    op.execute("ALTER TABLE granola_meetings RENAME COLUMN person_id TO employee_id")
    op.execute("ALTER TABLE notes RENAME COLUMN person_id TO employee_id")

    op.execute("ALTER TABLE people RENAME TO employees")
