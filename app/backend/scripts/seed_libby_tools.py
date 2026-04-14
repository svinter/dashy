"""Seed Libby library_entries from Google Sheets tools list.

Usage (run from app/backend/):
    venv/bin/python scripts/seed_libby_tools.py [--dry-run]

Sheet columns expected (first row = headers):
    name        — entry name
    type        — exercise / training / <anything else → tool>
    url         — Google Doc URL (extracts gdoc_id automatically)

Type mapping:
    exercise  → s  (Worksheet)
    training  → n  (Note)
    other     → t  (Tool)
"""

import re
import sys
import os
import sqlite3
import argparse
import logging

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.google_auth import get_google_credentials
from googleapiclient.discovery import build
from config import DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SHEET_ID = "1ZW6hPrU3kJPc6Qnt0jIdAJ7G0XfdCkSWB3v_c0Lo7iE"
DB_PATH = DATA_DIR / "dashboard.db"

_GDOC_RE = re.compile(r"/d/([a-zA-Z0-9_-]{20,})/")

TYPE_MAP = {
    "exercise":  "s",   # → Worksheet
    "training":  "n",   # → Note
    "concept":   "t",   # → Tool
    "agreement": "t",   # → Tool
}

TYPE_TABLE = {
    "s": "library_worksheets",
    "n": "library_notes",
    "t": "library_tools",
}


def extract_gdoc_id(url: str) -> str | None:
    if not url:
        return None
    m = _GDOC_RE.search(url)
    return m.group(1) if m else None


def fetch_sheet_rows(service) -> list[dict]:
    """Fetch all data rows from the sheet, using first row as headers."""
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range="A:Z",
    ).execute()

    values = result.get("values", [])
    if not values:
        logger.error("Sheet returned no data")
        return []

    headers = [h.strip().lower() for h in values[0]]
    logger.info("Sheet headers: %s", headers)

    rows = []
    for i, row in enumerate(values[1:], start=2):
        # Pad short rows to header length
        padded = row + [""] * (len(headers) - len(row))
        d = {headers[j]: padded[j].strip() for j in range(len(headers))}
        d["_row"] = i
        rows.append(d)

    return rows


def seed_tools(dry_run: bool = False) -> None:
    creds = get_google_credentials()
    service = build("sheets", "v4", credentials=creds)

    rows = fetch_sheet_rows(service)
    if not rows:
        return

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    # Check which type codes are registered in library_types
    registered = {
        r[0]: r[1]
        for r in db.execute("SELECT code, table_name FROM library_types").fetchall()
    }
    logger.info("Registered types: %s", list(registered.keys()))

    # Find name/type/url columns (flexible header names)
    def col(row: dict, *candidates: str) -> str:
        for c in candidates:
            if c in row:
                return row[c]
        return ""

    counts = {"t": 0, "s": 0, "n": 0}
    skipped_no_name = 0
    skipped_no_url = 0
    skipped_bad_type = 0
    inserted = 0

    for row in rows:
        name = col(row, "tool", "name", "title", "resource name")
        raw_type = col(row, "type", "type label", "category").lower().strip()
        url = col(row, "url", "google doc url", "doc url", "link", "google doc").strip()

        if not name:
            skipped_no_name += 1
            continue

        if not url:
            logger.warning("Row %d skipped — no URL: %r", row["_row"], name)
            skipped_no_url += 1
            continue

        # Map type
        type_code = TYPE_MAP.get(raw_type, "t")  # default → tool

        table_name = TYPE_TABLE.get(type_code)
        if type_code not in registered:
            logger.warning("Row %d skipped — type %r not registered", row["_row"], type_code)
            skipped_bad_type += 1
            continue

        gdoc_id = extract_gdoc_id(url)

        logger.info(
            "Row %d: %r → type=%s gdoc_id=%s",
            row["_row"], name, type_code, gdoc_id or "(none)"
        )

        if dry_run:
            counts[type_code] += 1
            inserted += 1
            continue

        # Check for duplicate by name+type_code
        existing = db.execute(
            "SELECT id FROM library_entries WHERE name = ? AND type_code = ?",
            (name, type_code),
        ).fetchone()
        if existing:
            logger.info("  Skip duplicate: %r", name)
            continue

        # Insert entity row
        cur = db.execute(f"INSERT INTO {table_name} (id) VALUES (NULL)")
        entity_id = cur.lastrowid

        # Insert library entry
        cur = db.execute(
            """INSERT INTO library_entries
               (name, type_code, url, gdoc_id, priority, entity_id,
                needs_enrichment, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'medium', ?, 1, datetime('now'), datetime('now'))""",
            (name, type_code, url or None, gdoc_id, entity_id),
        )
        db.commit()
        counts[type_code] += 1
        inserted += 1
        logger.info("  Inserted entry id=%d", cur.lastrowid)

    db.close()

    print("\n── Seed results ──────────────────────────")
    print(f"  Tools (t):      {counts['t']}")
    print(f"  Worksheets (s): {counts['s']}")
    print(f"  Notes (n):      {counts['n']}")
    print(f"  Total inserted: {inserted}")
    print(f"  Skipped — no name:  {skipped_no_name}")
    print(f"  Skipped — no URL:   {skipped_no_url}")
    print(f"  Skipped — bad type: {skipped_bad_type}")
    if dry_run:
        print("  (DRY RUN — nothing written)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Libby library from Google Sheet")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    args = parser.parse_args()
    seed_tools(dry_run=args.dry_run)
