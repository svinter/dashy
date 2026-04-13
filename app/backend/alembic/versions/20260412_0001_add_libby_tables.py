"""Add Libby library management tables

Revision ID: 20260412_0001
Revises: 20260411_0002
Create Date: 2026-04-12 00:01:00

Schema for the Libby module (personal library of resources).
Design document: ~/Obsidian/MyNotes/Projects/Dashy/libby-design.md

Tables created:
  library_types         — type registry (b=book, a=article, p=podcast, t=tool, w=webpage)
  library_topics        — topic taxonomy with short prefix-matchable codes
  library_books         — book-specific fields (author, isbn, publisher, year, edition)
  library_articles      — article-specific fields (author, publication, published_date)
  library_podcasts      — podcast-specific fields (show_name, episode, host, published_date)
  library_tools         — tool-specific fields (platform, pricing, vendor)
  library_webpages      — webpage-specific fields (site_name, author)
  library_entries       — master search surface; one row per resource, any type
  library_entry_topics  — many-to-many junction between entries and topics
  library_share_log     — audit log written by the `record` action
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260412_0001"
down_revision: Union[str, None] = "20260411_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS library_types (
            code        TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            table_name  TEXT NOT NULL
        )
    """)

    op.execute("""
        INSERT OR IGNORE INTO library_types (code, name, table_name) VALUES
            ('b', 'Book',     'library_books'),
            ('a', 'Article',  'library_articles'),
            ('p', 'Podcast',  'library_podcasts'),
            ('t', 'Tool',     'library_tools'),
            ('w', 'Webpage',  'library_webpages')
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS library_topics (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            code    TEXT NOT NULL UNIQUE,
            name    TEXT NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS library_books (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            author      TEXT,
            isbn        TEXT,
            publisher   TEXT,
            year        INTEGER,
            edition     TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS library_articles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            author          TEXT,
            publication     TEXT,
            published_date  TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS library_podcasts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            show_name       TEXT,
            episode         TEXT,
            host            TEXT,
            published_date  TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS library_tools (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            platform    TEXT,
            pricing     TEXT,
            vendor      TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS library_webpages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            site_name   TEXT,
            author      TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS library_entries (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT    NOT NULL,
            type_code           TEXT    NOT NULL REFERENCES library_types(code),
            priority            TEXT    NOT NULL DEFAULT 'medium',
            frequency           INTEGER NOT NULL DEFAULT 0,
            url                 TEXT,
            obsidian_link       TEXT,
            webpage_url         TEXT,
            gdoc_id             TEXT,
            gdoc_library_path   TEXT,
            comments            TEXT,
            entity_id           INTEGER NOT NULL,
            created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_library_entries_type
            ON library_entries (type_code)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_library_entries_priority
            ON library_entries (priority)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS library_entry_topics (
            entry_id    INTEGER NOT NULL REFERENCES library_entries(id),
            topic_id    INTEGER NOT NULL REFERENCES library_topics(id),
            PRIMARY KEY (entry_id, topic_id)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS library_share_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id        INTEGER NOT NULL REFERENCES library_entries(id),
            client_id       INTEGER NOT NULL,
            shared_at       TEXT    NOT NULL DEFAULT (datetime('now')),
            meeting_date    TEXT,
            actions_taken   TEXT
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_library_share_log_entry
            ON library_share_log (entry_id)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_library_share_log_client
            ON library_share_log (client_id)
    """)


def downgrade() -> None:
    # Drop in reverse dependency order
    op.execute("DROP TABLE IF EXISTS library_share_log")
    op.execute("DROP TABLE IF EXISTS library_entry_topics")
    op.execute("DROP TABLE IF EXISTS library_entries")
    op.execute("DROP TABLE IF EXISTS library_webpages")
    op.execute("DROP TABLE IF EXISTS library_tools")
    op.execute("DROP TABLE IF EXISTS library_podcasts")
    op.execute("DROP TABLE IF EXISTS library_articles")
    op.execute("DROP TABLE IF EXISTS library_books")
    op.execute("DROP TABLE IF EXISTS library_topics")
    op.execute("DROP TABLE IF EXISTS library_types")
