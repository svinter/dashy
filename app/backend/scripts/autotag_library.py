#!/usr/bin/env python3
"""
Bulk auto-tagger for non-book library entries with needs_enrichment = 1.
Uses the same Claude API tagging logic as the runtime background task.

Usage:
    python scripts/autotag_library.py --dry-run        # show counts only
    python scripts/autotag_library.py                  # run tagging
    python scripts/autotag_library.py --limit 50       # process up to 50 entries
    python scripts/autotag_library.py --type e         # only essays
"""

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = Path.home() / ".personal-dashboard/dashboard.db"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 500
SLEEP_BETWEEN = 0.1  # seconds between API calls
COMMIT_EVERY = 50

_TYPE_NAMES = {
    "b": "Book",        "a": "Article",    "e": "Essay",
    "p": "Podcast",     "v": "Video",      "m": "Movie",
    "t": "Tool",        "w": "Webpage",    "s": "Worksheet",
    "z": "Assessment",  "n": "Note",       "d": "Document",
    "f": "Framework",   "c": "Course",     "r": "Research",
    "q": "Quote",
}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def open_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def load_entries(db: sqlite3.Connection, type_code: str | None, limit: int | None) -> list[sqlite3.Row]:
    sql = """
        SELECT e.id, e.name, e.type_code, e.url, e.comments,
               COALESCE(lb.author, li.author) AS author
        FROM library_entries e
        LEFT JOIN library_books lb ON e.type_code = 'b' AND e.entity_id = lb.id
        LEFT JOIN library_items li ON e.type_code != 'b' AND e.entity_id = li.id
        WHERE e.needs_enrichment = 1
          AND e.type_code != 'b'
    """
    params: list = []
    if type_code:
        sql += " AND e.type_code = ?"
        params.append(type_code)
    sql += " ORDER BY e.id"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return db.execute(sql, params).fetchall()


def load_topics(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute("SELECT id, code, name FROM library_topics ORDER BY code").fetchall()


# ---------------------------------------------------------------------------
# Dry run summary
# ---------------------------------------------------------------------------

def dry_run(db: sqlite3.Connection, type_code: str | None, limit: int | None) -> None:
    rows = load_entries(db, type_code, limit)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["type_code"]] = counts.get(r["type_code"], 0) + 1

    print("Auto-tag Dry Run")
    print("================")
    print(f"Entries to process: {len(rows)}")
    print()
    for tc in sorted(counts):
        label = _TYPE_NAMES.get(tc, tc)
        print(f"  {tc}  {label:<12} {counts[tc]:4d}")
    print()
    if limit and len(rows) >= limit:
        print(f"Note: limited to {limit} entries — more may remain.")
    print()
    print("Run without --dry-run to process all entries.")


# ---------------------------------------------------------------------------
# Tagging
# ---------------------------------------------------------------------------

def build_prompt(entry: sqlite3.Row, topic_rows: list[sqlite3.Row]) -> str:
    topics_list = ", ".join(r["name"] for r in topic_rows)
    type_label = _TYPE_NAMES.get(entry["type_code"], entry["type_code"])

    lines = [
        f"Title: {entry['name']}",
        f"Type: {type_label}",
    ]
    if entry["author"]:
        lines.append(f"Author: {entry['author']}")
    if entry["url"]:
        lines.append(f"URL: {entry['url']}")
    if entry["comments"]:
        lines.append(f"Description: {entry['comments']}")

    resource_text = "\n".join(lines)

    return (
        "You are a library tagging assistant. Given this resource, suggest the most relevant topics "
        "from the list below.\n"
        "Return ONLY a JSON array of topic names that apply, choosing from this exact list:\n"
        f"{topics_list}\n\n"
        f"Resource:\n{resource_text}\n\n"
        'Return format: ["topic1", "topic2"] — no other text.'
    )


def tag_entry(
    entry: sqlite3.Row,
    topic_rows: list[sqlite3.Row],
    client,
) -> list[int]:
    """Call Claude and return a list of matched topic IDs."""
    prompt = build_prompt(entry, topic_rows)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()

    # Strip markdown code fence if present
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()

    matched_names: list[str] = json.loads(raw)
    if not isinstance(matched_names, list):
        raise ValueError(f"Expected list, got {type(matched_names).__name__}: {raw!r}")

    # Match names back to IDs (case-insensitive)
    name_to_id = {r["name"].lower(): r["id"] for r in topic_rows}
    matched_ids = []
    for name in matched_names:
        tid = name_to_id.get(name.lower())
        if tid is not None:
            matched_ids.append(tid)

    return matched_ids


def run_tagging(db: sqlite3.Connection, type_code: str | None, limit: int | None) -> None:
    import anthropic

    entries = load_entries(db, type_code, limit)
    topic_rows = load_topics(db)

    if not topic_rows:
        print("No topics defined in library_topics — nothing to tag.")
        return

    print(f"Topics available: {len(topic_rows)}")
    print(f"Entries to tag  : {len(entries)}")
    print()

    client = anthropic.Anthropic()

    tagged = 0
    failed = 0
    skipped = 0

    for i, entry in enumerate(entries, 1):
        entry_id = entry["id"]
        name = entry["name"]

        # Insert a processing log row (no unique constraint — plain insert)
        db.execute(
            """INSERT INTO libby_enrichment_log (entry_id, task, status, created_at, updated_at)
               VALUES (?, 'tags', 'processing', datetime('now'), datetime('now'))""",
            (entry_id,),
        )
        db.commit()

        try:
            matched_ids = tag_entry(entry, topic_rows, client)

            if matched_ids:
                for tid in matched_ids:
                    db.execute(
                        "INSERT OR IGNORE INTO library_entry_topics (entry_id, topic_id) VALUES (?, ?)",
                        (entry_id, tid),
                    )

            db.execute(
                "UPDATE library_entries SET needs_enrichment = 0 WHERE id = ?",
                (entry_id,),
            )
            db.execute(
                """UPDATE libby_enrichment_log
                   SET status = 'complete', updated_at = datetime('now')
                   WHERE entry_id = ? AND task = 'tags'""",
                (entry_id,),
            )
            db.commit()

            topic_count = len(matched_ids)
            print(f"  [{i}/{len(entries)}] {name!r}  → {topic_count} topic(s)")
            tagged += 1

        except Exception as exc:
            db.execute(
                """UPDATE libby_enrichment_log
                   SET status = 'failed', error = ?, updated_at = datetime('now')
                   WHERE entry_id = ? AND task = 'tags'""",
                (str(exc)[:500], entry_id),
            )
            db.commit()
            print(f"  [{i}/{len(entries)}] ERROR {name!r}: {exc}")
            failed += 1

        if i % COMMIT_EVERY == 0:
            db.commit()

        time.sleep(SLEEP_BETWEEN)

    db.commit()

    print()
    print(f"Done.  Tagged: {tagged}  Failed: {failed}  Skipped: {skipped}")
    if limit and len(entries) >= limit:
        print(f"Limit of {limit} reached — run again to continue.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk auto-tag non-book library entries.")
    parser.add_argument("--dry-run", action="store_true", help="Show counts only, no API calls.")
    parser.add_argument("--limit", type=int, default=None, help="Max entries to process.")
    parser.add_argument("--type", dest="type_code", default=None, help="Filter to one type_code (e.g. e, a, t).")
    args = parser.parse_args()

    db = open_db()

    if args.dry_run:
        dry_run(db, args.type_code, args.limit)
    else:
        run_tagging(db, args.type_code, args.limit)

    db.close()


if __name__ == "__main__":
    main()
