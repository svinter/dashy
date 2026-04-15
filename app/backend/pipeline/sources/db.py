"""
libby_pipeline/db.py — Database initialisation and data loading
Version 1.0
"""

import sqlite3
from pathlib import Path
from parse import BookRecord, UnresolvedRecord, normalize_title


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS library_types (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    table_name  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS library_topics (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    code    TEXT NOT NULL UNIQUE,
    name    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS library_books (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    author          TEXT,
    isbn            TEXT,
    publisher       TEXT,
    year            INTEGER,
    edition         TEXT,
    status          TEXT DEFAULT 'unread',
    cover_url       TEXT,
    google_books_id TEXT,
    highlights_path TEXT,
    summary_path    TEXT,
    gdoc_summary_id TEXT,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS library_articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    author          TEXT,
    publication     TEXT,
    published_date  TEXT
);

CREATE TABLE IF NOT EXISTS library_podcasts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    show_name       TEXT,
    episode         TEXT,
    host            TEXT,
    published_date  TEXT
);

CREATE TABLE IF NOT EXISTS library_tools (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform    TEXT,
    pricing     TEXT,
    vendor      TEXT
);

CREATE TABLE IF NOT EXISTS library_webpages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name   TEXT,
    author      TEXT
);

CREATE TABLE IF NOT EXISTS library_entries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    type_code           TEXT NOT NULL,
    priority            TEXT NOT NULL DEFAULT 'medium',
    frequency           INTEGER NOT NULL DEFAULT 0,
    url                 TEXT,
    amazon_url          TEXT,
    obsidian_link       TEXT,
    webpage_url         TEXT,
    gdoc_id             TEXT,
    gdoc_library_path   TEXT,
    comments            TEXT,
    entity_id           INTEGER NOT NULL,
    needs_enrichment    BOOLEAN DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS library_entry_topics (
    entry_id    INTEGER NOT NULL REFERENCES library_entries(id),
    topic_id    INTEGER NOT NULL REFERENCES library_topics(id),
    PRIMARY KEY (entry_id, topic_id)
);

CREATE TABLE IF NOT EXISTS library_unresolved (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT,
    author      TEXT,
    url         TEXT,
    raw_tags    TEXT,
    source      TEXT,
    raw_line    TEXT,
    notes       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS library_share_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id        INTEGER NOT NULL REFERENCES library_entries(id),
    client_id       INTEGER NOT NULL,
    shared_at       TEXT NOT NULL DEFAULT (datetime('now')),
    meeting_date    TEXT,
    actions_taken   TEXT
);
"""

SEED_TYPES = [
    ("b", "Book",    "library_books"),
    ("a", "Article", "library_articles"),
    ("p", "Podcast", "library_podcasts"),
    ("t", "Tool",    "library_tools"),
    ("w", "Webpage", "library_webpages"),
]

SEED_TOPICS = [
    ("le", "leadership"),    ("co", "coaching"),
    ("od", "organizational development"), ("te", "teaming"),
    ("ha", "happiness"),     ("ec", "economics"),
    ("ra", "racism"),        ("hi", "history"),
    ("fi", "fiction"),       ("sc", "science"),
    ("mi", "military"),      ("bi", "biography"),
    ("bu", "business"),      ("re", "resilience"),
    ("mn", "mindfulness"),   ("in", "influence"),
    ("de", "decision-making"),("cr", "creativity"),
    ("ph", "philosophy"),    ("py", "psychology"),
    ("ag", "aging"),         ("po", "politics"),
    ("em", "emotions"),      ("pu", "purpose"),
    ("st", "startups"),      ("en", "enneagram"),
]

# Map from ground_truth tags / Curated headings → topic codes
TAG_TO_TOPIC = {
    "leadership":       "le", "coaching":         "co",
    "team-coaching":    "co", "OD":               "od",
    "org-design":       "od", "teaming":          "te",
    "happiness":        "ha", "economics":        "ec",
    "racism":           "ra", "anti-racism":      "ra",
    "us-history":       "hi", "world-history":    "hi",
    "history":          "hi", "fiction":          "fi",
    "science":          "sc", "military":         "mi",
    "biography":        "bi", "business":         "bu",
    "resilience":       "re", "mindfulness":      "mn",
    "influence":        "in", "decision-making":  "de",
    "creativity":       "cr", "philosophy":       "ph",
    "psychology":       "py", "aging":            "ag",
    "dying":            "ag", "politics":         "po",
    "emotions":         "em", "EQ":               "em",
    "purpose":          "pu", "startups":         "st",
    "enneagram":        "en", "management":       "le",
    "intentionality":   "ph", "consciousness":    "ph",
    "thinking":         "ph", "criticalthinking":  "ph",
    "learning":         "bu", "society":          "hi",
    "religion":         "ph", "retirement":       "ag",
    "optimism":         "ha", "listening":        "co",
    "negotiation":      "in", "strategy":         "bu",
    "innovation":       "bu", "education":        "bu",
    "technology":       "bu",
}


# ── Init ──────────────────────────────────────────────────────────────────────

def init_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    for code, name, table in SEED_TYPES:
        conn.execute(
            "INSERT OR IGNORE INTO library_types(code, name, table_name) VALUES (?,?,?)",
            (code, name, table)
        )
    for code, name in SEED_TOPICS:
        conn.execute(
            "INSERT OR IGNORE INTO library_topics(code, name) VALUES (?,?)",
            (code, name)
        )
    conn.commit()
    conn.close()
    print("  Database schema initialised")


# ── Load ──────────────────────────────────────────────────────────────────────

def load_to_db(merged: dict, db_path: Path):
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()

    # Build topic code → id map
    cur.execute("SELECT code, id FROM library_topics")
    topic_id_map = dict(cur.fetchall())

    books_loaded      = 0
    unresolved_loaded = 0

    for book in merged["books"]:
        # Insert into library_books
        cur.execute("""
            INSERT INTO library_books
                (author, isbn, publisher, year, status)
            VALUES (?,?,?,?,?)
        """, (
            book.author, "", "", None, book.status
        ))
        book_id = cur.lastrowid

        # Insert into library_entries
        cur.execute("""
            INSERT INTO library_entries
                (name, type_code, priority, frequency, url, amazon_url,
                 comments, entity_id, needs_enrichment)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            book.title, "b", book.priority, 0,
            book.url, book.amazon_url,
            book.comments, book_id, 1
        ))
        entry_id = cur.lastrowid

        # Resolve and link topics
        topic_codes = set()
        for tag in book.tags:
            code = TAG_TO_TOPIC.get(tag)
            if code:
                topic_codes.add(code)
        for topic_name in book.topics:
            # Try to match heading text to a topic code
            for tag, code in TAG_TO_TOPIC.items():
                if tag.lower() in topic_name.lower():
                    topic_codes.add(code)

        for code in topic_codes:
            tid = topic_id_map.get(code)
            if tid:
                cur.execute(
                    "INSERT OR IGNORE INTO library_entry_topics(entry_id, topic_id) VALUES (?,?)",
                    (entry_id, tid)
                )

        books_loaded += 1
        if books_loaded % 200 == 0:
            conn.commit()
            print(f"    ...{books_loaded} books loaded")

    for rec in merged["unresolved"]:
        cur.execute("""
            INSERT INTO library_unresolved
                (name, author, url, raw_tags, source, raw_line, notes)
            VALUES (?,?,?,?,?,?,?)
        """, (
            rec.name, rec.author, rec.url,
            rec.raw_tags, rec.source, rec.raw_line, rec.notes
        ))
        unresolved_loaded += 1

    conn.commit()
    conn.close()
    print(f"  Books loaded:      {books_loaded}")
    print(f"  Unresolved loaded: {unresolved_loaded}")
