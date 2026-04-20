#!/usr/bin/env python3
"""Import Obsidian vault library files into the Libby library database.

Usage:
    python scripts/import_vault_library.py [--dry-run]

--dry-run   Print counts and sample entries without writing to the database.

Folder → type code mapping (all write to library_items):
    4 Library/Articles        → a (article)
    4 Library/HBR             → a (article)
    4 Library/Essays          → e (essay)
    4 Library/Exploring       → e (essay)
    4 Library/Papers          → r (research)
    4 Library/Coaching Papers → r (research)
    4 Library/Mgmt Papers     → r (research)
    4 Library/Notes           → n (note)
    4 Library/Podcasts        → p (podcast)
    4 Library/Courses         → c (course)
    4 Library/Exercises       → s (worksheet)
    4 Library/Google overflow → r (research)
    4 Library/Walkabout       → n (note)

Skip rules:
    - Filenames starting with "Copy of"
    - Body content under 50 chars
    - .csv files (any extension that is not .md)

Duplicate detection:
    - Normalized name (lowercase, collapsed whitespace) + type_code already in DB
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
DB_PATH = Path.home() / ".personal-dashboard" / "dashboard.db"

FOLDER_TYPE_MAP = {
    "4 Library/Articles":        "a",
    "4 Library/HBR":             "a",
    "4 Library/Essays":          "e",
    "4 Library/Exploring":       "e",
    "4 Library/Papers":          "r",
    "4 Library/Coaching Papers": "r",
    "4 Library/Mgmt Papers":     "r",
    "4 Library/Notes":           "n",
    "4 Library/Podcasts":        "p",
    "4 Library/Courses":         "c",
    "4 Library/Exercises":       "s",
    "4 Library/Google overflow": "r",
    "4 Library/Walkabout":       "n",
}


# ---------------------------------------------------------------------------
# Parsing helpers
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

            # First pass: simple key: scalar value
            current_key = None
            list_items: list[str] = []

            for raw_line in fm_block.split("\n"):
                line = raw_line.rstrip()

                # List continuation
                stripped = line.strip()
                if current_key and stripped.startswith("- "):
                    list_items.append(stripped[2:].strip().strip('"\''))
                    continue
                if current_key and list_items and not stripped:
                    # blank line ends list
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
                    # Expect list items on following lines
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
    """Resolve title: frontmatter title > first H1 > filename stem."""
    if meta.get("title") and isinstance(meta["title"], str):
        t = meta["title"].strip()
        if t:
            return t

    # First non-empty H1 heading
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            t = line[2:].strip()
            # Strip trailing .pdf / .PDF
            t = re.sub(r"\.pdf$", "", t, flags=re.IGNORECASE).strip()
            if t:
                return t

    # Fall back to filename stem, strip common extensions
    name = re.sub(r"\.(pdf|doc|docx|txt)$", "", stem, flags=re.IGNORECASE)
    return name.strip()


def extract_url(meta: dict, body: str) -> str | None:
    """Frontmatter url > first markdown link > first bare https:// URL in body."""
    if meta.get("url") and isinstance(meta["url"], str):
        u = meta["url"].strip()
        if u.startswith("http"):
            return u

    # First [text](url) in body
    m = re.search(r"\[([^\]]+)\]\((https?://[^\)]+)\)", body)
    if m:
        return m.group(2)

    # Bare URL
    m = re.search(r"https?://\S+", body)
    if m:
        url = m.group(0).rstrip(".,;)")
        return url

    return None


def extract_author(meta: dict, body: str) -> str | None:
    """Frontmatter author > Readwise pattern > 'by Name' near top of body."""
    if meta.get("author") and isinstance(meta["author"], str):
        a = meta["author"].strip()
        if a and a.lower() not in ("unknown", "n/a", ""):
            return a

    # Readwise: "- Author:: [[Name]]" or "- Author:: Name"
    m = re.search(r"-\s*Author::\s*(?:\[\[)?([^\]\n]+)(?:\]\])?", body[:1000])
    if m:
        a = m.group(1).strip().strip("[]")
        if 2 < len(a) < 80:
            return a

    # "by Author Name" in first 400 chars, after # headings or [title]
    snippet = re.sub(r"^#{1,6}[^\n]*", "", body[:400], flags=re.MULTILINE)
    m = re.search(
        r"\bby\s+([A-Z][a-zA-Z\-\.']+(?:\s+[A-Z][a-zA-Z\-\.']+){0,3})",
        snippet,
    )
    if m:
        a = m.group(1).strip()
        if 2 < len(a) < 60:
            return a

    return None


def extract_first_paragraph(body: str) -> str | None:
    """Return first substantive paragraph, max 300 chars."""
    # Drop image placeholders
    body = re.sub(r"\*\*==> picture.*?<==\*\*", "", body)
    # Drop H1–H6 lines
    body = re.sub(r"^#{1,6}\s.*", "", body, flags=re.MULTILINE)
    # Drop Readwise field lines "- Key:: value"
    body = re.sub(r"^[-*]\s+\w[\w\s]+::", "", body, flags=re.MULTILINE)
    # Drop horizontal rules
    body = re.sub(r"^_{3,}$", "", body, flags=re.MULTILINE)
    # Drop hashtag-only lines
    body = re.sub(r"^#\w+(\s+#\w+)*\s*$", "", body, flags=re.MULTILINE)

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]

    for p in paragraphs:
        # Too short
        if len(p) < 40:
            continue
        lines = [l.strip() for l in p.split("\n") if l.strip()]
        # Mostly bullet points → skip
        bullet_count = sum(1 for l in lines if l.startswith(("* ", "- ", "+ ", ">")))
        if bullet_count / max(len(lines), 1) > 0.6:
            continue
        # Looks like a title/heading cluster → skip
        if all(len(l) < 60 for l in lines) and len(lines) <= 3:
            continue

        text = " ".join(lines)  # flatten newlines within paragraph
        return text[:300].strip()

    return None


def normalize_name(name: str) -> str:
    """Lowercase, NFKD, collapse whitespace for duplicate detection."""
    name = unicodedata.normalize("NFKD", name)
    name = name.lower().strip()
    name = re.sub(r"\s+", " ", name)
    return name


# ---------------------------------------------------------------------------
# Tag → topic matching
# ---------------------------------------------------------------------------

def _build_tag_topic_map(topics: list[dict]) -> dict[str, int]:
    """Return a dict mapping lowercase tag strings → topic id."""
    mapping: dict[str, int] = {}
    for t in topics:
        code = t["code"].lower()
        name = t["name"].lower()
        mapping[code] = t["id"]
        mapping[name] = t["id"]
        # Also map individual words in multi-word names
        for word in name.split():
            if len(word) >= 4:
                mapping.setdefault(word, t["id"])
    return mapping


def match_tags_to_topics(
    tags: list[str], tag_topic_map: dict[str, int]
) -> list[int]:
    """Return a deduplicated list of topic IDs matching the given tags."""
    matched: set[int] = set()
    for tag in tags:
        tag = tag.lower().strip().lstrip("#")
        if tag in tag_topic_map:
            matched.add(tag_topic_map[tag])
        else:
            # Try stripping common prefixes / suffixes
            tag_clean = re.sub(r"[-_]", " ", tag)
            if tag_clean in tag_topic_map:
                matched.add(tag_topic_map[tag_clean])
    return sorted(matched)


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def collect_files() -> list[dict]:
    """Walk all configured folders and return a list of parsed file records."""
    records: list[dict] = []
    skip_counts: dict[str, int] = {
        "not_md": 0,
        "copy_of": 0,
        "too_short": 0,
        "folder_missing": 0,
    }

    for folder_rel, type_code in FOLDER_TYPE_MAP.items():
        folder = VAULT_ROOT / folder_rel
        if not folder.exists():
            print(f"  WARNING: folder not found: {folder}")
            skip_counts["folder_missing"] += 1
            continue

        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue

            # Only .md files
            if path.suffix.lower() != ".md":
                skip_counts["not_md"] += 1
                continue

            # Skip "Copy of" files
            if path.name.startswith("Copy of"):
                skip_counts["copy_of"] += 1
                continue

            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            meta, body = parse_frontmatter(text)

            # Skip files with too little body content
            body_clean = body.strip()
            if len(body_clean) < 50:
                skip_counts["too_short"] += 1
                continue

            title = extract_title(meta, body, path.stem)
            url = extract_url(meta, body)
            author = extract_author(meta, body)
            comments = extract_first_paragraph(body)
            tags = meta.get("tags", [])
            if isinstance(tags, str):
                tags = [tags]

            records.append({
                "path": path,
                "folder": folder_rel,
                "type_code": type_code,
                "title": title,
                "url": url,
                "author": author,
                "comments": comments,
                "tags": tags,
            })

    return records, skip_counts


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def load_existing(db: sqlite3.Connection) -> set[tuple[str, str]]:
    """Return a set of (normalized_name, type_code) tuples already in the DB."""
    rows = db.execute("SELECT name, type_code FROM library_entries").fetchall()
    return {(normalize_name(r[0]), r[1]) for r in rows}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Import vault library files into Libby.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be imported without writing.")
    args = parser.parse_args()

    print(f"Vault root : {VAULT_ROOT}")
    print(f"Database   : {DB_PATH}")
    print(f"Mode       : {'DRY RUN' if args.dry_run else 'LIVE IMPORT'}")
    print()

    # Collect files
    print("Scanning folders…")
    records, skip_counts = collect_files()
    print(f"  Files scanned  : {sum(skip_counts.values()) + len(records)}")
    print(f"  Non-md skipped : {skip_counts['not_md']}")
    print(f"  'Copy of' skip : {skip_counts['copy_of']}")
    print(f"  Too short skip : {skip_counts['too_short']}")
    print(f"  Candidates     : {len(records)}")
    print()

    # Connect to DB
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # Load topics for tag matching
    topics = [dict(r) for r in db.execute("SELECT id, code, name FROM library_topics").fetchall()]
    tag_topic_map = _build_tag_topic_map(topics)

    # Load existing entries for duplicate detection
    existing = load_existing(db)
    print(f"Existing library entries (all types): {len(existing)}")
    print()

    # Classify records
    to_import: list[dict] = []
    duplicates: list[dict] = []

    for rec in records:
        key = (normalize_name(rec["title"]), rec["type_code"])
        if key in existing:
            duplicates.append(rec)
        else:
            rec["topic_ids"] = match_tags_to_topics(rec["tags"], tag_topic_map)
            to_import.append(rec)

    # Summary by folder
    print("── Breakdown by folder ──────────────────────────────")
    folder_stats: dict[str, dict] = {}
    for rec in records:
        f = rec["folder"]
        if f not in folder_stats:
            folder_stats[f] = {"total": 0, "import": 0, "dup": 0}
        folder_stats[f]["total"] += 1

    for rec in to_import:
        folder_stats[rec["folder"]]["import"] += 1
    for rec in duplicates:
        folder_stats[rec["folder"]]["dup"] += 1

    for folder, stats in sorted(folder_stats.items()):
        label = folder.replace("4 Library/", "")
        tc = FOLDER_TYPE_MAP[folder]
        print(f"  {label:<22} ({tc})  total={stats['total']:3d}  import={stats['import']:3d}  dup={stats['dup']:2d}")

    print()
    print(f"Total to import : {len(to_import)}")
    print(f"Total duplicates: {len(duplicates)}")
    print()

    # Sample entries
    print("── Sample entries (first 5 to import) ──────────────")
    for rec in to_import[:5]:
        print(f"  [{rec['type_code']}] {rec['title'][:60]}")
        if rec["author"]:
            print(f"        author  : {rec['author']}")
        if rec["url"]:
            print(f"        url     : {rec['url'][:70]}")
        if rec["comments"]:
            print(f"        excerpt : {rec['comments'][:80]}…")
        if rec["topic_ids"]:
            matched = [t["code"] for t in topics if t["id"] in rec["topic_ids"]]
            print(f"        topics  : {', '.join(matched)}")
        print()

    if args.dry_run:
        print("── DRY RUN complete — no changes written ────────────")
        db.close()
        return

    # ── Live import ──────────────────────────────────────────────────────────
    print("── Importing… ───────────────────────────────────────")
    imported = 0
    errors = 0

    for rec in to_import:
        try:
            with db:
                # Insert into library_items
                cur = db.execute(
                    "INSERT INTO library_items (author) VALUES (?)",
                    (rec["author"],),
                )
                entity_id = cur.lastrowid

                # Insert into library_entries
                cur2 = db.execute(
                    """INSERT INTO library_entries
                       (name, type_code, url, comments, priority, entity_id,
                        needs_enrichment, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'medium', ?, 1, datetime('now'), datetime('now'))""",
                    (rec["title"], rec["type_code"], rec["url"], rec["comments"], entity_id),
                )
                entry_id = cur2.lastrowid

                # Assign matched topics
                for tid in rec["topic_ids"]:
                    db.execute(
                        "INSERT OR IGNORE INTO library_entry_topics (entry_id, topic_id) VALUES (?, ?)",
                        (entry_id, tid),
                    )

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
