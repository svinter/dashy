#!/usr/bin/env python3
"""update_vault_stubs.py — Backfill enrichment data into existing Obsidian vault stubs.

For each book with obsidian_link set and enrichment data in library_books:
  - Reads the existing .md file
  - Updates YAML frontmatter to fill in any missing fields:
      isbn, publisher, year (as 'publish'), status, topics
  - Does NOT overwrite existing frontmatter values
  - Does NOT touch body content below the frontmatter
  - Skips files where all target fields are already present

Usage:
  cd /Users/stevevinter/dashy/app/backend
  python scripts/update_vault_stubs.py
"""

import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote

DB_PATH = Path.home() / ".personal-dashboard" / "dashboard.db"
VAULT_ROOT = Path.home() / "Obsidian" / "MyNotes"

# Fields we want to ensure are present in frontmatter
TARGET_FIELDS = {"isbn", "publisher", "publish", "status", "topics"}


def parse_frontmatter(text: str) -> tuple[dict[str, str], int]:
    """Return (raw_fields_dict, end_offset) where end_offset points past closing ---."""
    if not text.startswith("---"):
        return {}, 0
    end = text.find("---", 3)
    if end == -1:
        return {}, 0
    fm_block = text[3:end]
    fields: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()
    return fields, end + 3


def obsidian_link_to_path(link: str) -> Path | None:
    """Convert obsidian://open?vault=...&file=... to absolute filesystem path."""
    if not link or "file=" not in link:
        return None
    try:
        file_part = link.split("file=", 1)[1]
        rel = unquote(file_part)
        return VAULT_ROOT / rel
    except Exception:
        return None


def load_books(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT
            e.id,
            e.name,
            e.obsidian_link,
            b.isbn,
            b.publisher,
            b.year,
            b.status AS book_status
        FROM library_entries e
        JOIN library_books b ON b.id = e.entity_id
        WHERE e.type_code = 'b'
          AND e.obsidian_link IS NOT NULL
          AND e.obsidian_link != ''
    """)
    books = [dict(r) for r in cur.fetchall()]

    # Fetch topics for each entry
    if books:
        entry_ids = [b["id"] for b in books]
        ph = ",".join("?" * len(entry_ids))
        topic_rows = cur.execute(
            f"""SELECT jet.entry_id, lt.name
                FROM library_entry_topics jet
                JOIN library_topics lt ON jet.topic_id = lt.id
                WHERE jet.entry_id IN ({ph})""",
            entry_ids,
        ).fetchall()
        topics_by_entry: dict[int, list[str]] = {}
        for tr in topic_rows:
            topics_by_entry.setdefault(tr[0], []).append(tr[1])
        for b in books:
            b["topics"] = topics_by_entry.get(b["id"], [])

    conn.close()
    return books


def update_file(path: Path, missing: dict[str, str]) -> bool:
    """Insert missing frontmatter fields into the file. Returns True if modified."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"    WARN: cannot read {path}: {e}")
        return False

    if not text.startswith("---"):
        # No frontmatter — prepend one
        fm_lines = ["---"]
        for k, v in missing.items():
            fm_lines.append(f"{k}: {v}")
        fm_lines.append("---")
        fm_lines.append("")
        new_text = "\n".join(fm_lines) + "\n" + text
        path.write_text(new_text, encoding="utf-8")
        return True

    # Find end of frontmatter block
    end = text.find("---", 3)
    if end == -1:
        return False

    fm_block = text[3:end]
    insert_lines: list[str] = []
    for k, v in missing.items():
        insert_lines.append(f"{k}: {v}")

    # Insert before the closing ---
    new_fm = fm_block.rstrip("\n") + "\n" + "\n".join(insert_lines) + "\n"
    new_text = "---" + new_fm + "---" + text[end + 3:]
    path.write_text(new_text, encoding="utf-8")
    return True


def main():
    if not DB_PATH.exists():
        print(f"ERROR: database not found at {DB_PATH}")
        sys.exit(1)

    books = load_books(DB_PATH)
    print(f"Loaded {len(books)} books with obsidian_link set")

    updated = 0
    skipped_complete = 0
    skipped_no_file = 0
    sample: dict | None = None  # store one before/after for reporting

    for book in books:
        path = obsidian_link_to_path(book["obsidian_link"])
        if not path or not path.exists():
            skipped_no_file += 1
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            skipped_no_file += 1
            continue

        existing, _ = parse_frontmatter(text)
        existing_keys_lower = {k.lower() for k in existing}

        # Build what's missing
        missing: dict[str, str] = {}

        isbn = (book.get("isbn") or "").strip()
        if isbn and "isbn" not in existing_keys_lower:
            missing["isbn"] = isbn

        publisher = (book.get("publisher") or "").strip()
        if publisher and "publisher" not in existing_keys_lower:
            missing["publisher"] = f'"{publisher}"'

        year = book.get("year")
        if year and "publish" not in existing_keys_lower:
            missing["publish"] = str(year)

        status = (book.get("book_status") or "unread").strip()
        if status and "status" not in existing_keys_lower:
            missing["status"] = status

        topics: list[str] = book.get("topics", [])
        if topics and "topics" not in existing_keys_lower:
            missing["topics"] = "[" + ", ".join(topics) + "]"

        if not missing:
            skipped_complete += 1
            continue

        # Capture sample before/after
        before_fm = None
        if sample is None:
            before_fm = "\n".join(
                line for line in text.splitlines()
                if text.splitlines().index(line) < 20
            ) if text.startswith("---") else "(no frontmatter)"

        if update_file(path, missing):
            updated += 1
            if sample is None and before_fm is not None:
                after_text = path.read_text(encoding="utf-8", errors="ignore")
                after_fm = "\n".join(after_text.splitlines()[:20])
                sample = {
                    "name": book["name"],
                    "path": str(path),
                    "added": list(missing.keys()),
                    "before": before_fm,
                    "after": after_fm,
                }

    print(f"\nResults:")
    print(f"  Updated:           {updated}")
    print(f"  Already complete:  {skipped_complete}")
    print(f"  File not found:    {skipped_no_file}")

    if sample:
        print(f"\nSample — {sample['name']}")
        print(f"  Path: {sample['path']}")
        print(f"  Fields added: {', '.join(sample['added'])}")
        print(f"\n  BEFORE (first 20 lines):\n{sample['before']}")
        print(f"\n  AFTER (first 20 lines):\n{sample['after']}")
    else:
        print("\n(No sample — all files were already complete or not found)")


if __name__ == "__main__":
    main()
