#!/usr/bin/env python3
"""Match highlight .md files in Obsidian vault to library_books and update highlights_path.

Usage:
    python scripts/match_highlights.py --dry-run   # show matches without writing
    python scripts/match_highlights.py --apply     # write high-confidence matches to DB
"""

import argparse
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

VAULT_ROOT = Path("/Users/stevevinter/Obsidian/MyNotes")
HIGHLIGHTS_DIR = VAULT_ROOT / "4 Library/Highlights"
DB_PATH = Path.home() / ".personal-dashboard/dashboard.db"

HIGH_CONFIDENCE = 85
NEEDS_REVIEW = 65

_TIMESTAMP_RE = re.compile(r" - highlights-\d+\.md$")
_PLAIN_RE = re.compile(r" - highlights\.md$")


def strip_suffix(filename: str) -> str:
    """Remove ' - highlights.md' or ' - highlights-{digits}.md' suffix."""
    name = _TIMESTAMP_RE.sub("", filename)
    name = _PLAIN_RE.sub("", name)
    return name


def is_plain(filename: str) -> bool:
    """Return True if this is the plain (non-timestamped) form."""
    return bool(_PLAIN_RE.search(filename))


def normalize(name: str) -> str:
    """Normalize for fuzzy matching."""
    name = name.replace("-", " ").replace(":", " ").strip()
    if name.lower().startswith("the "):
        name = name[4:]
    return name.lower()


def score(a: str, b: str) -> int:
    return int(SequenceMatcher(None, normalize(a), normalize(b)).ratio() * 100)


def main():
    parser = argparse.ArgumentParser(description="Match highlight files to library_books.")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args()

    if not args.apply:
        args.dry_run = True

    # Load highlight files — prefer plain form over timestamped when both exist
    all_files = sorted(HIGHLIGHTS_DIR.glob("*.md"))
    if not all_files:
        print(f"No .md files found in {HIGHLIGHTS_DIR}")
        return

    # Deduplicate: for each stripped title, keep plain form if available
    by_title: dict[str, Path] = {}
    for f in all_files:
        title = strip_suffix(f.name)
        if title not in by_title or is_plain(f.name):
            by_title[title] = f

    highlight_files = sorted(by_title.values(), key=lambda p: p.name)

    # Load books from DB (need entity_id to update library_books)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    books = conn.execute(
        "SELECT e.id AS entry_id, e.name, e.entity_id AS book_id "
        "FROM library_entries e "
        "WHERE e.type_code = 'b'"
    ).fetchall()

    if not books:
        print("No book records found in library_entries (type_code='b')")
        conn.close()
        return

    high, review, none_ = [], [], []

    for hf in highlight_files:
        candidate = strip_suffix(hf.name)
        best_score = 0
        best_book = None
        for book in books:
            s = score(candidate, book["name"])
            if s > best_score:
                best_score = s
                best_book = book

        rel_path = str(hf.relative_to(VAULT_ROOT))
        entry = (hf.name, best_book, best_score, rel_path)

        if best_score >= HIGH_CONFIDENCE:
            high.append(entry)
        elif best_score >= NEEDS_REVIEW:
            review.append(entry)
        else:
            none_.append(entry)

    # --- Report ---
    print("Highlights Matching Dry Run" if args.dry_run else "Highlights Matching — APPLYING")
    print("=" * 40)

    print(f"\nHIGH CONFIDENCE (≥{HIGH_CONFIDENCE}):")
    for fname, book, s, rel in high:
        print(f'  "{fname}"')
        print(f'  → "{book["name"]}" (id={book["entry_id"]}, score={s})')

    print(f"\nNEEDS REVIEW ({NEEDS_REVIEW}–{HIGH_CONFIDENCE - 1}):")
    for fname, book, s, rel in review:
        print(f'  "{fname}"')
        print(f'  → "{book["name"]}" (id={book["entry_id"]}, score={s})')

    print(f"\nNO MATCH (<{NEEDS_REVIEW}):")
    for fname, book, s, rel in none_:
        reason = f'best match: "{book["name"]}" (score={s})' if book else "no books in DB"
        print(f'  "{fname}" — {reason}')

    print(f"\nTOTALS:")
    print(f"  High confidence: {len(high)}")
    print(f"  Needs review:    {len(review)}")
    print(f"  No match:        {len(none_)}")

    if not args.dry_run and args.apply:
        updated = 0
        for fname, book, s, rel in high:
            conn.execute(
                "UPDATE library_books SET highlights_path = ? WHERE id = ?",
                (rel, book["book_id"]),
            )
            updated += 1
        conn.commit()
        print(f"\nUpdated {updated} rows.")

    conn.close()


if __name__ == "__main__":
    main()
