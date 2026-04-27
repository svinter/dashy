#!/usr/bin/env python3
"""Sync DB metadata into vault book page YAML frontmatter.

Fields synced (DB → vault):
  status        library_books.status
  publish       library_books.year
  isbn          library_books.isbn
  date_finished library_books.date_finished (added if not present, only when non-null)

Author is NOT overwritten — vault uses [[Author]] wikilink format.
Any field already matching the DB value is left untouched (no spurious writes).

Usage:
  python scripts/update_vault_metadata.py [--dry-run]
"""

import argparse
import re
import sqlite3
from pathlib import Path
from urllib.parse import unquote

VAULT_ROOT = Path("/Users/stevevinter/Obsidian/MyNotes")
DB_PATH = Path.home() / ".personal-dashboard/dashboard.db"

_FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (fields_dict, body_after_fm).  fields_dict is raw line-by-line."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm_text = m.group(1)
    body = text[m.end():]
    fields: dict[str, str] = {}
    for line in fm_text.splitlines():
        if ": " in line:
            key, _, val = line.partition(": ")
            fields[key.strip()] = val.strip()
        elif line.endswith(":"):
            fields[line[:-1].strip()] = ""
    return fields, body


def _set_field(fm_text: str, key: str, new_val: str) -> str:
    """Update or append a scalar field in raw frontmatter text."""
    pattern = re.compile(rf"^({re.escape(key)}:\s*)(.*)$", re.MULTILINE)
    if pattern.search(fm_text):
        return pattern.sub(rf"\g<1>{new_val}", fm_text)
    # Field missing — append before closing ---
    return fm_text.rstrip("\n") + f"\n{key}: {new_val}"


def _rebuild_file(fm_text: str, body: str) -> str:
    return f"---\n{fm_text}\n---\n{body}"


def _obsidian_link_to_path(link: str) -> Path | None:
    m = re.search(r"[?&]file=([^&]+)", link)
    if not m:
        return None
    return VAULT_ROOT / unquote(m.group(1))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    books = conn.execute("""
        SELECT e.id, e.name, e.type_code, e.obsidian_link,
               lb.author, lb.year, lb.isbn, lb.status, lb.date_finished
        FROM library_entries e
        JOIN library_books lb ON lb.id = e.entity_id
        WHERE e.type_code = 'b'
          AND e.obsidian_link IS NOT NULL AND e.obsidian_link != ''
        ORDER BY e.name
    """).fetchall()

    conn.close()

    total = len(books)
    updated = 0
    skipped_no_file = 0
    skipped_no_fm = 0
    unchanged = 0
    sample_diffs: list[dict] = []

    for book in books:
        vault_path = _obsidian_link_to_path(book["obsidian_link"])
        if not vault_path or not vault_path.exists():
            skipped_no_file += 1
            continue

        original = vault_path.read_text(encoding="utf-8")
        fields, body = _parse_frontmatter(original)
        if not fields:
            skipped_no_fm += 1
            continue

        fm_match = _FM_RE.match(original)
        fm_text = fm_match.group(1) if fm_match else ""

        changes: list[tuple[str, str, str]] = []  # (field, old, new)

        def _check(field: str, db_val, vault_key: str | None = None) -> None:
            nonlocal fm_text
            vk = vault_key or field
            if db_val is None:
                return
            db_str = str(db_val).strip()
            if not db_str:
                return
            vault_str = fields.get(vk, "").strip().strip('"').strip("'")
            if vault_str != db_str:
                changes.append((vk, vault_str, db_str))
                fm_text = _set_field(fm_text, vk, db_str)

        _check("status", book["status"])
        _check("publish", book["year"])
        _check("isbn", book["isbn"])
        if book["date_finished"]:
            _check("date_finished", book["date_finished"])

        if not changes:
            unchanged += 1
            continue

        new_content = _rebuild_file(fm_text, body)

        diff_str = "; ".join(
            f'{f}: "{o}" → "{n}"' for f, o, n in changes
        )

        if len(sample_diffs) < 3:
            sample_diffs.append({
                "name": book["name"],
                "path": str(vault_path.relative_to(VAULT_ROOT)),
                "changes": changes,
            })

        if not args.dry_run:
            vault_path.write_text(new_content, encoding="utf-8")

        updated += 1

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------
    mode = "DRY RUN — " if args.dry_run else ""
    print(f"{mode}Vault Metadata Update")
    print("=" * 40)
    print(f"Total linked books:     {total:>5,}")
    print(f"Would update:           {updated:>5,}  (at least one field differs)")
    print(f"Already up-to-date:     {unchanged:>5,}")
    print(f"Vault file missing:     {skipped_no_file:>5,}")
    print(f"No frontmatter:         {skipped_no_fm:>5,}")
    print()

    if sample_diffs:
        print("Sample diffs:")
        for s in sample_diffs:
            print(f"\n  {s['name']}")
            print(f"  File: {s['path']}")
            for field, old, new in s["changes"]:
                old_disp = f'"{old}"' if old else "(missing)"
                print(f"    {field}: {old_disp} → \"{new}\"")

    if args.dry_run:
        print("\n(dry run — no files written)")
    else:
        print(f"\nWrote {updated} vault files.")


if __name__ == "__main__":
    main()
