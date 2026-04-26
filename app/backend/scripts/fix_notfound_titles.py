#!/usr/bin/env python3
"""Fix not-found book titles and reset for re-enrichment.

Usage:
    python scripts/fix_notfound_titles.py [--dry-run]
"""

import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".personal-dashboard/dashboard.db"

# skip=True  → leave in not-found log, no enrichment reset
# author     → also update library_books.author
FIXES: dict[int, dict] = {
    2362: {"name": "3 Days, 9 Months, 27 Years"},
    3066: {"name": "Ann Patchett books", "skip": True},
    2453: {"name": "Back Roads Northern & Central Italy", "skip": True},
    2590: {"name": "Historians' Fallacies"},
    2645: {"name": "Life as We Knew It"},
    2682: {"name": "Naomi's Gift"},
    2707: {"name": "Outside Looking In"},
    2710: {"name": "Perilous Times"},
    2715: {"name": "Power Down"},
    2725: {"name": "Raising an Emotionally Intelligent Child", "author": "John Gottman"},
    2757: {"name": "Something Deeply Hidden"},
    3003: {"name": "To Speak for the Dead"},
    2779: {"name": "Tender Is the Night"},
    2783: {"name": "That Month in Tuscany"},
    2807: {"name": "The Best of Tony Robbins", "skip": True},
    2826: {"name": "The Clementine Complex"},
    2828: {"name": "The Collapsing Empire"},
    2843: {"name": "The Faithful Spy"},
    3097: {"name": "The House of Doors"},
    2889: {"name": "The Last Black Unicorn"},
    3063: {"name": "The Lovely Bones"},
    3080: {"name": "The Magnolia Palace"},
    2906: {"name": "The Myth of Sisyphus"},
    2927: {"name": "The Pattern on the Stone"},
    3061: {"name": "The Power of Moments"},
    2965: {"name": "The Tainted Cup"},
    2986: {"name": "The Will of the Many"},
    3028: {"name": "We Hunt the Flame"},
    3102: {"name": "We Solve Murders"},
    3034: {"name": "What Do You Do With an Idea?"},
    3043: {"name": "White Tiger"},
    3084: {"name": "You Are Here"},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    fixed = 0
    skipped = 0
    not_in_db = 0

    for entry_id, fix in FIXES.items():
        row = conn.execute(
            "SELECT e.id, e.name, e.entity_id FROM library_entries e WHERE e.id = ?",
            (entry_id,),
        ).fetchone()

        if not row:
            print(f"  MISSING  id={entry_id}  (not in library_entries)")
            not_in_db += 1
            continue

        name = fix["name"]
        is_skip = fix.get("skip", False)
        author = fix.get("author")

        if is_skip:
            print(f"  SKIP     id={entry_id}  {row['name']!r}")
            skipped += 1
            continue

        print(f"  FIX      id={entry_id}  {row['name']!r} → {name!r}" +
              (f"  author={author!r}" if author else ""))

        if not args.dry_run:
            conn.execute(
                "UPDATE library_entries SET name = ?, updated_at = datetime('now') WHERE id = ?",
                (name, entry_id),
            )
            conn.execute(
                "UPDATE library_entries SET needs_enrichment = 1 WHERE id = ?",
                (entry_id,),
            )
            conn.execute(
                "DELETE FROM library_enrich_not_found WHERE entry_id = ?",
                (entry_id,),
            )
            if author:
                conn.execute(
                    "UPDATE library_books SET author = ? WHERE id = ?",
                    (author, row["entity_id"]),
                )
        fixed += 1

    if not args.dry_run:
        conn.commit()

    conn.close()

    print()
    print(f"{'DRY RUN — ' if args.dry_run else ''}Results:")
    print(f"  Fixed (queued for re-enrichment): {fixed}")
    print(f"  Skipped (left in not-found log):  {skipped}")
    print(f"  Not in DB:                        {not_in_db}")


if __name__ == "__main__":
    main()
