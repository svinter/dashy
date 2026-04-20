"""Collapse all non-book type tables into a single library_items table.

Each source table has its own AUTOINCREMENT sequence starting at 1, so IDs
overlap across tables and cannot be bulk-inserted directly. We migrate
row-by-row: insert into library_items (new autoincrement id), then update
library_entries.entity_id to point at the new id.

Revision ID: 20260420_0001
Revises:     20260418_0003
"""

revision = "20260420_0001"
down_revision = "20260418_0003"
branch_labels = None
depends_on = None

from alembic import op  # noqa: E402
from sqlalchemy import text  # noqa: E402


def upgrade():
    conn = op.get_bind()

    # Create library_items (may already exist from earlier manual creation)
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS library_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            author          TEXT,
            publication     TEXT,
            published_date  TEXT,
            show_name       TEXT,
            episode         TEXT,
            host            TEXT,
            platform        TEXT,
            pricing         TEXT,
            vendor          TEXT,
            site_name       TEXT,
            text            TEXT,
            attribution     TEXT,
            context         TEXT,
            notes           TEXT
        )
    """))

    # Tables with data: migrate row-by-row, assigning new IDs and remapping entity_id.
    # IDs overlap across source tables (all start at 1), so we cannot bulk-insert.
    tables_with_data = [
        ('t', 'library_tools'),
        ('q', 'library_quotes'),
        ('s', 'library_worksheets'),
        ('n', 'library_notes'),
        ('e', 'library_essays'),
    ]
    for type_code, old_table in tables_with_data:
        rows = conn.execute(text(f"SELECT id FROM {old_table} ORDER BY id")).fetchall()
        for (old_id,) in rows:
            result = conn.execute(text("INSERT INTO library_items (id) VALUES (NULL)"))
            new_id = result.lastrowid
            conn.execute(
                text("UPDATE library_entries SET entity_id = :new_id WHERE type_code = :tc AND entity_id = :old_id"),
                {"new_id": new_id, "tc": type_code, "old_id": old_id},
            )

    # Point all non-book types at library_items
    conn.execute(text("UPDATE library_types SET table_name = 'library_items' WHERE code != 'b'"))

    # Drop old type-specific tables
    for tbl in [
        "library_tools", "library_quotes", "library_worksheets",
        "library_notes", "library_essays", "library_articles",
        "library_podcasts", "library_webpages", "library_assessments",
        "library_courses", "library_documents", "library_frameworks",
        "library_movies", "library_research", "library_videos",
    ]:
        conn.execute(text(f"DROP TABLE IF EXISTS {tbl}"))


def downgrade():
    conn = op.get_bind()

    # Recreate original tables (empty — data not restored on downgrade)
    for ddl in [
        "CREATE TABLE library_articles    (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_assessments (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_courses     (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_documents   (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_essays      (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_frameworks  (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_movies      (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_notes       (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_podcasts    (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_quotes      (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_research    (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_tools       (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_videos      (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_webpages    (id INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE library_worksheets  (id INTEGER PRIMARY KEY AUTOINCREMENT)",
    ]:
        conn.execute(text(ddl))

    conn.execute(text("DROP TABLE IF EXISTS library_items"))

    for code, tbl in [
        ("a", "library_articles"), ("c", "library_courses"), ("d", "library_documents"),
        ("e", "library_essays"), ("f", "library_frameworks"), ("m", "library_movies"),
        ("n", "library_notes"), ("p", "library_podcasts"), ("q", "library_quotes"),
        ("r", "library_research"), ("s", "library_worksheets"), ("t", "library_tools"),
        ("v", "library_videos"), ("w", "library_webpages"), ("z", "library_assessments"),
    ]:
        conn.execute(text(f"UPDATE library_types SET table_name = '{tbl}' WHERE code = '{code}'"))
