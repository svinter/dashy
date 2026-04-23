#!/usr/bin/env python3
"""Match summary .md files in Obsidian vault to library_entries and update summary_path."""

import argparse
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

VAULT_ROOT = Path("/Users/stevevinter/Obsidian/MyNotes")
SUMMARIES_DIR = VAULT_ROOT / "4 Library/Summaries"
DB_PATH = Path.home() / ".personal-dashboard/dashboard.db"

HIGH_CONFIDENCE = 85
NEEDS_REVIEW = 65


def normalize(name: str) -> str:
    """Normalize a name for fuzzy matching."""
    name = name.removesuffix(".md")
    name = name.removesuffix(" Summary")
    name = name.replace("-", " ")
    name = name.strip()
    # Strip leading "The " for matching
    if name.lower().startswith("the "):
        name = name[4:]
    return name.lower()


def score(a: str, b: str) -> int:
    return int(SequenceMatcher(None, normalize(a), normalize(b)).ratio() * 100)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args()

    if not args.apply:
        args.dry_run = True

    # Load summary files
    summary_files = sorted(SUMMARIES_DIR.glob("*.md"))
    if not summary_files:
        print(f"No .md files found in {SUMMARIES_DIR}")
        return

    # Load books from DB
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    books = conn.execute(
        "SELECT id, name FROM library_entries WHERE type_code = 'b'"
    ).fetchall()

    if not books:
        print("No book records found in library_entries (type_code='b')")
        conn.close()
        return

    high, review, none_ = [], [], []

    for sf in summary_files:
        best_score = 0
        best_book = None
        for book in books:
            s = score(sf.name, book["name"])
            if s > best_score:
                best_score = s
                best_book = book

        # Relative vault path
        rel_path = str(sf.relative_to(VAULT_ROOT))

        entry = (sf.name, best_book, best_score, rel_path)
        if best_score >= HIGH_CONFIDENCE:
            high.append(entry)
        elif best_score >= NEEDS_REVIEW:
            review.append(entry)
        else:
            none_.append(entry)

    # --- Report ---
    print("Summary Matching Dry Run" if args.dry_run else "Summary Matching — APPLYING")
    print("=" * 40)

    print(f"\nHIGH CONFIDENCE (≥{HIGH_CONFIDENCE}):")
    for fname, book, s, rel in high:
        print(f'  "{fname}"')
        print(f'  → "{book["name"]}" (id={book["id"]}, score={s})')

    print(f"\nNEEDS REVIEW ({NEEDS_REVIEW}–{HIGH_CONFIDENCE - 1}):")
    for fname, book, s, rel in review:
        print(f'  "{fname}"')
        print(f'  → "{book["name"]}" (id={book["id"]}, score={s})')

    print(f"\nNO MATCH (<{NEEDS_REVIEW}):")
    for fname, book, s, rel in none_:
        reason = f"best match: \"{book['name']}\" (score={s})" if book else "no books in DB"
        print(f'  "{fname}" — {reason}')

    print(f"\nTOTALS:")
    print(f"  High confidence: {len(high)}")
    print(f"  Needs review:    {len(review)}")
    print(f"  No match:        {len(none_)}")

    if not args.dry_run and args.apply:
        updated = 0
        for fname, book, s, rel in high:
            conn.execute(
                "UPDATE library_entries SET summary_path = ? WHERE id = ?",
                (rel, book["id"]),
            )
            updated += 1
        conn.commit()
        print(f"\nUpdated {updated} rows.")

    conn.close()


if __name__ == "__main__":
    main()
