#!/usr/bin/env python3
"""Import Obsidian Coaching library files into the Libby library database.

Usage:
    python scripts/import_coaching_library.py [--dry-run]

--dry-run   Print counts and folder breakdown without writing to the database.

Folder → (type_code, private) mapping under 4 Library/Coaching/:
    See FOLDER_MAPPINGS below.

Duplicate detection:
    - obsidian_link already in library_entries.obsidian_link
"""

import argparse
import re
import sqlite3
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VAULT_ROOT = Path("/Users/stevevinter/Obsidian/MyNotes")
COACHING_ROOT = VAULT_ROOT / "4 Library/Coaching"
DB_PATH = Path.home() / ".personal-dashboard/dashboard.db"

# Folder → (type_code, private)
# More-specific paths must come before their parent directories.
FOLDER_MAPPINGS = [
    ("Assessments/Predictive Insights",         "z", True),
    ("Assessments/My InspireCorps Assessment",  "z", True),
    ("Assessments/FIRO - Cathy Chen",           "z", True),
    ("Assessments/Insights Discovery",          "z", True),
    ("Assessments/Lumiere Sciences",            "z", True),
    ("Assessments/Enneagram",                   "z", False),
    ("Assessments/MBTI",                        "z", False),
    ("Assessments/StrengthsFinder",             "z", False),
    ("Assessments/Leadership Circle",           "z", False),
    ("Assessments/Korn Ferry",                  "z", False),
    ("Assessments/Reflection Exercises",        "s", False),
    ("Tools/Business docs",                     "t", True),
    ("Tools/Engagements",                       "t", True),
    ("Tools/Templates",                         "s", False),
    ("Tools",                                   "t", False),
    ("OD/Worksheets",                           "s", False),
    ("OD/Readings",                             "r", False),
    ("OD/Playbooks",                            "t", False),
    ("OD/Content",                              "r", False),
    ("OD/Facilitation",                         "t", False),
    ("OD/Ice Breakers",                         "t", False),
    ("OD/Adaptive Leadership Workshop",         "t", False),
    ("OD",                                      "t", False),
    ("Social Justice",                          "r", False),
    ("Anti-Racism",                             "r", False),
    ("PQ",                                      "t", False),
    ("NASA Notes",                              "n", True),
    ("Aging",                                   "r", False),
    ("Elder Odyssey",                           "n", True),
    ("Leadership Immersion",                    "n", True),
    ("Retirement",                              "r", False),
    ("Purpose",                                 "t", False),
    ("Product Management",                      "r", False),
    ("Art & Practice of Leadership Dev",        "t", False),
]


# ---------------------------------------------------------------------------
# Type/privacy resolution
# ---------------------------------------------------------------------------

def get_type_and_privacy(file_path: Path) -> tuple[str, bool]:
    """Return (type_code, private) based on folder prefix matching."""
    rel = str(file_path.relative_to(COACHING_ROOT))
    for folder, type_code, private in FOLDER_MAPPINGS:
        if rel.startswith(folder):
            return type_code, private
    return "u", False


# ---------------------------------------------------------------------------
# Parsing helpers (reused from import_vault_library.py)
# ---------------------------------------------------------------------------

def _strip_bom(text: str) -> str:
    return text.lstrip("\ufeff")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (meta dict, body text). Handles YAML frontmatter blocks."""
    text = _strip_bom(text)
    meta: dict = {}

    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm_block = text[3:end]
            body = text[end + 4:].lstrip("\n")

            current_key = None
            list_items: list[str] = []

            for raw_line in fm_block.split("\n"):
                line = raw_line.rstrip()

                stripped = line.strip()
                if current_key and stripped.startswith("- "):
                    list_items.append(stripped[2:].strip().strip('"\''))
                    continue
                if current_key and list_items and not stripped:
                    meta[current_key] = list_items
                    current_key = None
                    list_items = []
                    continue

                if ":" not in stripped:
                    continue

                key, _, val = stripped.partition(":")
                key = key.strip().lower()
                val = val.strip().strip("'\"")

                if key not in ("title", "author", "url", "tags", "date", "created", "type",
                               "aliases", "category"):
                    continue

                if val == "" or val == "[]":
                    current_key = key
                    list_items = []
                elif val.startswith("[") and val.endswith("]"):
                    items = [t.strip().strip("'\"") for t in val[1:-1].split(",")]
                    meta[key] = [i for i in items if i]
                else:
                    meta[key] = val

            if current_key and list_items:
                meta[current_key] = list_items

            return meta, body

    return meta, text


def extract_title(meta: dict, body: str, stem: str) -> str:
    """Resolve title: frontmatter title → frontmatter aliases[0] → first H1 → filename stem."""
    # frontmatter title (may be a list in some vaults)
    raw = meta.get("title") or ""
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    t = str(raw).strip()
    if t:
        return t

    # frontmatter aliases[0]
    aliases = meta.get("aliases") or []
    if isinstance(aliases, list) and aliases:
        t = str(aliases[0]).strip()
        if t:
            return t

    # first H1 heading in body
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            t = line[2:].strip()
            t = re.sub(r"\.pdf$", "", t, flags=re.IGNORECASE).strip()
            if t:
                return t

    # filename stem (clean up hyphens/underscores)
    name = re.sub(r"\.(pdf|doc|docx|txt)$", "", stem, flags=re.IGNORECASE)
    return name.strip()


def extract_url(meta: dict, body: str) -> str | None:
    """Frontmatter url > first markdown link > first bare https:// URL in body."""
    if meta.get("url") and isinstance(meta["url"], str):
        u = meta["url"].strip()
        if u.startswith("http"):
            return u

    m = re.search(r"\[([^\]]+)\]\((https?://[^\)]+)\)", body)
    if m:
        return m.group(2)

    m = re.search(r"https?://\S+", body)
    if m:
        url = m.group(0).rstrip(".,;)")
        return url

    return None


def normalize_name(name: str) -> str:
    """Lowercase, NFKD, collapse whitespace for duplicate detection."""
    name = unicodedata.normalize("NFKD", name)
    name = name.lower().strip()
    name = re.sub(r"\s+", " ", name)
    return name


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def collect_files() -> tuple[list[dict], dict[str, int]]:
    """Walk all files under COACHING_ROOT and return parsed records."""
    if not COACHING_ROOT.exists():
        print(f"  ERROR: Coaching root not found: {COACHING_ROOT}")
        return [], {}

    records: list[dict] = []
    skip_counts: dict[str, int] = {
        "not_md": 0,
        "copy_of": 0,
        "unmapped": 0,
    }

    for path in sorted(COACHING_ROOT.rglob("*")):
        if not path.is_file():
            continue

        if path.suffix.lower() != ".md":
            skip_counts["not_md"] += 1
            continue

        if path.name.startswith("Copy of"):
            skip_counts["copy_of"] += 1
            continue

        type_code, private = get_type_and_privacy(path)
        if type_code == "u":
            skip_counts["unmapped"] += 1
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        meta, body = parse_frontmatter(text)
        title = extract_title(meta, body, path.stem)
        url = extract_url(meta, body)

        # obsidian_link: full obsidian:// URL, used as unique key and for opening
        from urllib.parse import quote as _quote
        rel = str(path.relative_to(VAULT_ROOT))
        encoded = "/".join(_quote(part, safe="") for part in rel.split("/"))
        obsidian_link = f"obsidian://open?vault=MyNotes&file={encoded}"

        records.append({
            "path": path,
            "type_code": type_code,
            "private": private,
            "title": title,
            "url": url,
            "obsidian_link": obsidian_link,
        })

    return records, skip_counts


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def load_existing_obsidian_links(db: sqlite3.Connection) -> set[str]:
    """Return a set of obsidian_link values already in the DB."""
    rows = db.execute(
        "SELECT obsidian_link FROM library_entries WHERE obsidian_link IS NOT NULL"
    ).fetchall()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Import Coaching library files into Libby.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be imported without writing.")
    args = parser.parse_args()

    print(f"Vault root     : {VAULT_ROOT}")
    print(f"Coaching root  : {COACHING_ROOT}")
    print(f"Database       : {DB_PATH}")
    print(f"Mode           : {'DRY RUN' if args.dry_run else 'LIVE IMPORT'}")
    print()

    print("Scanning files…")
    records, skip_counts = collect_files()
    print(f"  Non-md skipped : {skip_counts.get('not_md', 0)}")
    print(f"  'Copy of' skip : {skip_counts.get('copy_of', 0)}")
    print(f"  Unmapped skip  : {skip_counts.get('unmapped', 0)}")
    print(f"  Candidates     : {len(records)}")
    print()

    # Connect to DB
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # Load existing obsidian_link values for duplicate detection
    existing_links = load_existing_obsidian_links(db)
    print(f"Existing entries with obsidian_link: {len(existing_links)}")
    print()

    # Classify records
    to_import: list[dict] = []
    duplicates: list[dict] = []

    for rec in records:
        if rec["obsidian_link"] in existing_links:
            duplicates.append(rec)
        else:
            to_import.append(rec)

    # Breakdown by folder
    print("── Breakdown by folder ──────────────────────────────────────────────")

    # Build folder stats from records
    folder_stats: dict[str, dict] = {}
    for rec in records:
        rel = str(rec["path"].relative_to(COACHING_ROOT))
        # Determine which mapping matched
        matched_folder = "(other)"
        for folder, type_code, private in FOLDER_MAPPINGS:
            if rel.startswith(folder):
                matched_folder = folder
                break
        key = matched_folder
        if key not in folder_stats:
            folder_stats[key] = {"total": 0, "import": 0, "dup": 0, "type_code": "?", "private": False}
            for folder, tc, priv in FOLDER_MAPPINGS:
                if folder == matched_folder:
                    folder_stats[key]["type_code"] = tc
                    folder_stats[key]["private"] = priv
                    break
        folder_stats[key]["total"] += 1

    for rec in to_import:
        rel = str(rec["path"].relative_to(COACHING_ROOT))
        matched_folder = "(other)"
        for folder, _, _ in FOLDER_MAPPINGS:
            if rel.startswith(folder):
                matched_folder = folder
                break
        if matched_folder in folder_stats:
            folder_stats[matched_folder]["import"] += 1

    for rec in duplicates:
        rel = str(rec["path"].relative_to(COACHING_ROOT))
        matched_folder = "(other)"
        for folder, _, _ in FOLDER_MAPPINGS:
            if rel.startswith(folder):
                matched_folder = folder
                break
        if matched_folder in folder_stats:
            folder_stats[matched_folder]["dup"] += 1

    for folder, stats in sorted(folder_stats.items()):
        priv_flag = " [private]" if stats["private"] else ""
        print(
            f"  {folder:<42} ({stats['type_code']}){priv_flag:<10}"
            f"  total={stats['total']:3d}  import={stats['import']:3d}  dup={stats['dup']:2d}"
        )

    print()
    print(f"Total to import : {len(to_import)}")
    print(f"Total duplicates: {len(duplicates)}")
    print()

    if args.dry_run:
        print("── DRY RUN complete — no changes written ──────────────────────────")
        db.close()
        return

    # ── Live import ──────────────────────────────────────────────────────────
    print("── Importing… ───────────────────────────────────────────────────────")
    imported = 0
    errors = 0

    for rec in to_import:
        try:
            with db:
                # Insert into library_items (author optional — set null)
                cur = db.execute(
                    "INSERT INTO library_items (author) VALUES (?)",
                    (None,),
                )
                entity_id = cur.lastrowid

                # Insert into library_entries
                cur2 = db.execute(
                    """INSERT INTO library_entries
                       (name, type_code, url, comments, priority, entity_id,
                        needs_enrichment, private, obsidian_link,
                        created_at, updated_at)
                       VALUES (?, ?, ?, NULL, 'medium', ?, 0, ?, ?,
                               datetime('now'), datetime('now'))""",
                    (
                        rec["title"],
                        rec["type_code"],
                        rec["url"],
                        entity_id,
                        int(rec["private"]),
                        rec["obsidian_link"],
                    ),
                )
                _ = cur2.lastrowid

            imported += 1
            if imported % 50 == 0:
                print(f"  …{imported} imported")

        except Exception as exc:
            print(f"  ERROR importing {rec['title']!r}: {exc}")
            errors += 1

    print()
    print(f"Done. Imported: {imported}  Errors: {errors}  Skipped (dup): {len(duplicates)}")
    db.close()


if __name__ == "__main__":
    main()
