#!/usr/bin/env python3
"""Create stub vault pages for books missing obsidian_link.

Generates a minimal .md with YAML frontmatter in 4 Library/Books/.
Skips if the file already exists.
Updates library_entries.obsidian_link in DB after creation.

Usage:
  python scripts/create_missing_book_stubs.py [--dry-run]
"""

import argparse
import re
import sqlite3
from pathlib import Path

VAULT_ROOT = Path("/Users/stevevinter/Obsidian/MyNotes")
BOOKS_FOLDER = VAULT_ROOT / "4 Library/Books"
DB_PATH = Path.home() / ".personal-dashboard/dashboard.db"


def _safe_filename(name: str) -> str:
    """Convert a book title to a safe filename (no path-illegal chars)."""
    # Remove characters that are illegal in macOS/Obsidian filenames
    s = re.sub(r'[/\\:*?"<>|]', "", name)
    # Collapse runs of spaces/dots at the end
    s = s.strip(". ")
    return s or "Untitled"


def _obsidian_link(rel: str) -> str:
    return f"obsidian://open?vault=MyNotes&file={rel}"


def _make_frontmatter(name: str, author: str | None, year, isbn: str | None,
                      status: str | None, genre: str | None,
                      date_finished: str | None, url: str | None) -> str:
    lines = ["---", 'type:', '  - book']

    # Title — quote if it contains special chars
    safe_title = name.replace('"', '\\"')
    lines.append(f'title: "{safe_title}"')

    if author:
        safe_author = author.replace('"', '\\"')
        lines.append(f'author: "{safe_author}"')

    if url:
        lines.append(f'URL: {url}')

    if isbn:
        lines.append(f'isbn: {isbn}')

    if year:
        lines.append(f'publish: {year}')

    if status:
        lines.append(f'status: {status}')

    if genre:
        lines.append(f'genre: {genre}')

    if date_finished:
        lines.append(f'date_finished: {date_finished}')

    lines.append("---")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    books = conn.execute("""
        SELECT e.id, e.name, e.url,
               lb.author, lb.year, lb.isbn, lb.status, lb.genre, lb.date_finished
        FROM library_entries e
        JOIN library_books lb ON lb.id = e.entity_id
        WHERE e.type_code = 'b'
          AND (e.obsidian_link IS NULL OR e.obsidian_link = '')
        ORDER BY e.name
    """).fetchall()

    total = len(books)
    created = 0
    skipped_exists = 0
    errors = 0

    print(f"{'DRY RUN — ' if args.dry_run else ''}Create Missing Book Stubs")
    print("=" * 45)
    print(f"Books missing obsidian_link: {total:,}")
    print()

    for book in books:
        filename = _safe_filename(book["name"]) + ".md"
        dest = BOOKS_FOLDER / filename
        rel = f"4 Library/Books/{filename}"
        link = _obsidian_link(rel)

        if dest.exists():
            skipped_exists += 1
            # Still update DB link if missing
            if not args.dry_run:
                conn.execute(
                    "UPDATE library_entries SET obsidian_link = ?, updated_at = datetime('now') WHERE id = ?",
                    (link, book["id"]),
                )
            continue

        fm = _make_frontmatter(
            name=book["name"],
            author=book["author"],
            year=book["year"],
            isbn=book["isbn"],
            status=book["status"] or "unread",
            genre=book["genre"],
            date_finished=book["date_finished"],
            url=book["url"],
        )
        content = fm + "\n"

        if args.dry_run:
            if created < 5:
                print(f"  WOULD CREATE: {filename}")
                print(f"    author={book['author']!r}  year={book['year']}  "
                      f"isbn={book['isbn']!r}  status={book['status']!r}")
        else:
            try:
                dest.write_text(content, encoding="utf-8")
                conn.execute(
                    "UPDATE library_entries SET obsidian_link = ?, updated_at = datetime('now') WHERE id = ?",
                    (link, book["id"]),
                )
                created += 1
            except Exception as exc:
                print(f"  ERROR: {filename}: {exc}")
                errors += 1
                continue

        if not args.dry_run:
            pass  # already incremented above
        else:
            created += 1  # count for dry-run totals

    if not args.dry_run:
        conn.commit()
    conn.close()

    print()
    print("Results:")
    print(f"  {'Would create' if args.dry_run else 'Created'}:      {created:>5,}")
    print(f"  Dest exists (link updated): {skipped_exists:>5,}")
    if errors:
        print(f"  Errors:        {errors:>5,}")
    print()
    if args.dry_run:
        print("(dry run — no files written, no DB updates)")


if __name__ == "__main__":
    main()
