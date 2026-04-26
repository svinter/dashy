#!/usr/bin/env python3
"""Import reading list spreadsheet into Libby library_books / library_entries.

Usage:
    python scripts/import_reading_list.py [--dry-run] [--file PATH]

Options:
    --dry-run   Print stats and preview without writing to the database.
    --file      Path to the .xlsx spreadsheet (default: scripts/sources/Copy__Books.xlsx)

Matching logic:
    - Normalize title (lowercase, strip subtitle after ':', strip punctuation)
    - Fuzzy match against library_entries.name where type_code = 'b'
    - Score >= 85  →  UPDATE existing library_books row with spreadsheet fields
    - Score < 85   →  INSERT new library_entries + library_books rows

For matched books, status is only overwritten if the spreadsheet value is more
informative than the existing value (e.g. 'read' beats 'unread', but 'unread'
will not overwrite 'read').
"""

import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = Path.home() / ".personal-dashboard/dashboard.db"
SCRIPT_DIR = Path(__file__).parent
DEFAULT_XLSX = SCRIPT_DIR / "sources" / "Copy__Books.xlsx"

STATUS_MAP: dict[str, str] = {
    "to read":    "unread",
    "read":       "read",
    "in progress": "reading",
    "started":    "reading",
    "canceled":   "abandoned",
    "abandoned":  "abandoned",
}

GENRE_MAP: dict[str, str] = {
    "fiction":    "fiction",
    "nonfiction": "nonfiction",
    "coaching":   "coaching",
}

# Status ordering — higher rank is more informative / further along
STATUS_RANK: dict[str, int] = {
    "unread":    1,
    "reading":   2,
    "abandoned": 3,
    "read":      4,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_title(title: str) -> str:
    """Lowercase, strip subtitle after ':', strip punctuation, collapse spaces."""
    t = title.lower()
    colon = t.find(":")
    if colon > 0:
        t = t[:colon]
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _map_status(raw) -> str:
    if pd.isna(raw) or raw is None:
        return "unread"
    return STATUS_MAP.get(str(raw).strip().lower(), "unread")


def _map_genre(raw) -> str | None:
    if pd.isna(raw) or raw is None:
        return None
    return GENRE_MAP.get(str(raw).strip().lower())


def _map_priority(raw) -> int | None:
    if pd.isna(raw) or raw is None:
        return None
    try:
        return int(float(str(raw).strip()))
    except (ValueError, TypeError):
        return None


def _map_date(raw) -> str | None:
    if pd.isna(raw) or raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.strftime("%Y-%m-%d")
    s = str(raw).strip()
    if s:
        return s
    return None


def _map_str(raw) -> str | None:
    if pd.isna(raw) or raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def _status_is_more_informative(new: str, existing: str) -> bool:
    """Return True if new status has higher rank than existing."""
    return STATUS_RANK.get(new, 0) > STATUS_RANK.get(existing, 0)


# ---------------------------------------------------------------------------
# Spreadsheet parsing
# ---------------------------------------------------------------------------

SECTION_HEADERS = {"reading", "read", "queue", "to read", "in progress", "abandoned"}


def parse_spreadsheet(path: Path) -> list[dict]:
    """Parse the Books.xlsx spreadsheet.

    Returns a list of dicts with keys:
        title, author, genre, reading_priority, status,
        date_finished, owned_format, reading_notes

    Column detection strategy:
    - Named fields (Author, Type, Status, etc.) are matched by exact keyword.
    - Title column: prefer an exact 'Title' match; if that column has <50%
      non-null fill rate, fall back to the densest non-standard column.
      Explicitly ignore 'Title + Author' (it's a pre-combined redundant column).
    - Unnamed col 0 carries section headers (READING, READ, 2026, etc.).
    """
    df = pd.read_excel(path, header=0)

    # Preserve original names for get() lookups; build stripped copies for matching.
    orig_cols = list(df.columns)
    stripped = [str(c).strip() for c in orig_cols]
    # Map stripped name → original name (first occurrence wins for dupes)
    strip_to_orig: dict[str, str] = {}
    for orig, s in zip(orig_cols, stripped):
        if s not in strip_to_orig:
            strip_to_orig[s] = orig
    df.columns = stripped  # work with stripped names hereafter

    KNOWN_FIELDS = {"author", "type", "prioritity", "priority", "status",
                    "finished", "comments", "owned?", "unnamed: 0",
                    "title + author", "title"}

    col_map: dict[str, str] = {}
    for col in stripped:
        cl = col.lower()
        if cl == "title":
            col_map.setdefault("title_exact", col)
        elif cl == "author":
            col_map["author"] = col
        elif cl in ("type", "genre"):
            col_map["genre"] = col
        elif "prior" in cl:
            col_map["priority"] = col
        elif cl == "status":
            col_map["status"] = col
        elif cl in ("finished",):
            col_map["date_finished"] = col
        elif cl == "owned?":
            col_map["owned_format"] = col
        elif cl == "comments":
            col_map["reading_notes"] = col

    # Title column resolution: use exact "Title" only if ≥50% fill; otherwise
    # pick the densest non-standard, non-unnamed column.
    n_rows = len(df)
    exact_title = col_map.get("title_exact")
    if exact_title and df[exact_title].notna().sum() >= n_rows * 0.5:
        col_map["title"] = exact_title
    else:
        # Find densest column that isn't a known/named field
        best_col, best_count = None, 0
        for col in stripped:
            if col.lower() in KNOWN_FIELDS:
                continue
            if col.lower().startswith("unnamed"):
                continue
            count = df[col].notna().sum()
            if count > best_count:
                best_count = count
                best_col = col
        if best_col:
            col_map["title"] = best_col
        elif exact_title:
            col_map["title"] = exact_title

    if "title" not in col_map:
        raise ValueError(
            f"Could not find a Title column in {path}.\n"
            f"Available columns: {stripped}"
        )

    # Section-header col (unnamed col 0)
    unnamed_col = next((c for c in stripped if c.lower().startswith("unnamed")), None)

    rows = []
    for _, row in df.iterrows():
        # Skip rows where unnamed col 0 is a section header or year label
        if unnamed_col:
            label = row.get(unnamed_col)
            if not pd.isna(label):
                label_s = str(label).strip()
                if (label_s.lower() in SECTION_HEADERS
                        or re.match(r'^\s*\d{4}\s*$', label_s)):
                    continue

        title_raw = row.get(col_map["title"])

        # Skip blank rows
        if pd.isna(title_raw) or str(title_raw).strip() == "":
            continue

        title = str(title_raw).strip()

        # Skip template header rows ("TITLE") and section headers
        if title.upper() == "TITLE":
            continue
        if title.lower() in SECTION_HEADERS:
            continue
        # Skip year labels ("2026", "  2025  ", etc.)
        if re.match(r'^\s*\d{4}\s*$', title):
            continue

        rows.append({
            "title":            title,
            "author":           _map_str(row.get(col_map.get("author"))),
            "genre":            _map_genre(row.get(col_map.get("genre"))),
            "reading_priority": _map_priority(row.get(col_map.get("priority"))),
            "status":           _map_status(row.get(col_map.get("status"))),
            "date_finished":    _map_date(row.get(col_map.get("date_finished"))),
            "owned_format":     _map_str(row.get(col_map.get("owned_format"))),
            "reading_notes":    _map_str(row.get(col_map.get("reading_notes"))),
        })

    return rows


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def load_catalog(conn: sqlite3.Connection) -> list[dict]:
    """Load all book entries from the DB for fuzzy matching."""
    rows = conn.execute("""
        SELECT e.id AS entry_id, e.name, b.id AS book_id, b.status, b.author
        FROM library_entries e
        JOIN library_books b ON b.id = e.entity_id
        WHERE e.type_code = 'b'
    """).fetchall()
    return [
        {
            "entry_id":  r[0],
            "name":      r[1],
            "book_id":   r[2],
            "status":    r[3],
            "author":    r[4],
            "norm":      _normalize_title(r[1]),
        }
        for r in rows
    ]


def find_match(title: str, catalog: list[dict]) -> dict | None:
    """Fuzzy-match a title against the catalog. Returns best match or None."""
    norm = _normalize_title(title)
    best_score = 0
    best = None
    for entry in catalog:
        score = fuzz.token_set_ratio(norm, entry["norm"])
        if score > best_score:
            best_score = score
            best = entry
    if best_score >= 85:
        return best
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(xlsx_path: Path, dry_run: bool) -> None:
    if not xlsx_path.exists():
        print(f"\nERROR: Spreadsheet not found at: {xlsx_path}")
        print(
            "Copy the file there and try again:\n"
            f"  cp ~/Downloads/Copy__Books.xlsx {xlsx_path}\n"
        )
        sys.exit(1)

    print(f"Parsing {xlsx_path} …")
    rows = parse_spreadsheet(xlsx_path)

    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    catalog = load_catalog(conn)

    matched: list[tuple[dict, dict]] = []   # (spreadsheet_row, catalog_entry)
    new_books: list[dict] = []
    skipped_no_title: int = 0

    for row in rows:
        if not row["title"]:
            skipped_no_title += 1
            continue
        m = find_match(row["title"], catalog)
        if m:
            matched.append((row, m))
        else:
            new_books.append(row)

    # -------------------------------------------------------------------------
    # Dry run report
    # -------------------------------------------------------------------------
    if dry_run:
        status_counts: dict[str, int] = {}
        for r, _ in matched:
            status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

        genre_counts: dict[str, int] = {}
        for r in new_books:
            g = r["genre"] or "unknown"
            genre_counts[g] = genre_counts.get(g, 0) + 1

        print()
        print("Reading List Import Dry Run")
        print("=" * 44)
        print(f"Total rows parsed:     {len(rows)}")
        print(f"Matched to catalog:    {len(matched)}  (will UPDATE)")
        print(f"New books:             {len(new_books)}  (will INSERT)")
        print(f"Skipped (no title):    {skipped_no_title}")
        print()
        print("Status breakdown of matched:")
        for status in ("read", "unread", "reading", "abandoned"):
            count = status_counts.get(status, 0)
            if count:
                print(f"  {status:<10} {count}")
        print()
        print("New books by genre:")
        for genre in sorted(genre_counts):
            print(f"  {genre:<12} {genre_counts[genre]}")
        print()

        if new_books:
            print("Sample new books (first 10):")
            for r in new_books[:10]:
                author_str = f" by {r['author']}" if r["author"] else ""
                print(f"  {r['title']}{author_str}")
        conn.close()
        return

    # -------------------------------------------------------------------------
    # Live run
    # -------------------------------------------------------------------------
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updates = 0
    inserts = 0

    for row, entry in matched:
        existing_status = entry["status"] or "unread"
        new_status = row["status"]
        final_status = (
            new_status if _status_is_more_informative(new_status, existing_status)
            else existing_status
        )
        conn.execute("""
            UPDATE library_books SET
                date_finished    = COALESCE(?, date_finished),
                owned_format     = COALESCE(?, owned_format),
                reading_priority = COALESCE(?, reading_priority),
                reading_notes    = COALESCE(?, reading_notes),
                genre            = COALESCE(?, genre),
                date_added       = ?,
                status           = ?
            WHERE id = ?
        """, (
            row["date_finished"],
            row["owned_format"],
            row["reading_priority"],
            row["reading_notes"],
            row["genre"],
            now,
            final_status,
            entry["book_id"],
        ))
        updates += 1

    for row in new_books:
        # Insert library_books row first
        cur = conn.execute("""
            INSERT INTO library_books
                (author, status, date_finished, owned_format, reading_priority,
                 reading_notes, genre, date_added)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["author"],
            row["status"],
            row["date_finished"],
            row["owned_format"],
            row["reading_priority"],
            row["reading_notes"],
            row["genre"],
            now,
        ))
        book_id = cur.lastrowid

        priority = "high" if row["reading_priority"] == 1 else "medium"

        conn.execute("""
            INSERT INTO library_entries
                (name, type_code, priority, frequency, entity_id, needs_enrichment, created_at, updated_at)
            VALUES (?, 'b', ?, 0, ?, 1, ?, ?)
        """, (
            row["title"],
            priority,
            book_id,
            now,
            now,
        ))
        inserts += 1

    conn.commit()
    conn.close()

    print(f"Done. Updated {updates} existing books, inserted {inserts} new books.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import reading list spreadsheet into Libby.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--file", default=str(DEFAULT_XLSX), help="Path to .xlsx file")
    args = parser.parse_args()

    run(Path(args.file), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
