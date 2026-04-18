"""
libby_pipeline/vault.py — Vault reconciliation
Version 1.0

Handles:
  - Scanning 4 Library/Books/ and linking to DB entries
  - Scanning rest of vault for content-bearing book files
  - Fuzzy matching against DB titles
  - Generating and applying the review YAML
  - Creating stub .md files for books with no vault entry
"""

import re
import sqlite3
import shutil
import yaml
import difflib
from pathlib import Path
from datetime import date


# ── Constants ─────────────────────────────────────────────────────────────────

STUB_TEMPLATE = """\
---
tag: book
title: "{title}"
author: [{author}]
subtitle: {subtitle}
authors: [{authors}]
publisher: {publisher}
publish: {year}
isbn: {isbn}
categories: [{categories}]
status: {status}
url: {url}
amazon_url: {amazon_url}
preview_link: {preview_link}
topics: [{topics}]
created: {created_at}
updated: {updated_at}
---

# {title}
"""

MIN_CONTENT_CHARS = 200   # below this threshold = empty stub


# ── Title normalisation (shared with parse.py) ────────────────────────────────

def normalize_title(title: str) -> str:
    title = title.split(":")[0]
    title = re.sub(r"[^\w\s]", "", title)
    return title.strip().lower()


def title_from_path(path: Path) -> str:
    """Derive normalized title from filename."""
    return normalize_title(path.stem)


# ── Vault body extraction ─────────────────────────────────────────────────────

def extract_body(path: Path) -> str:
    """Return markdown body with frontmatter stripped."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

    # Strip YAML frontmatter
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:]
    return text.strip()


def extract_frontmatter(path: Path) -> dict:
    """Parse YAML frontmatter if present."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}

    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(text[3:end]) or {}
    except Exception:
        return {}


def has_meaningful_content(path: Path) -> bool:
    body = extract_body(path)
    return len(body) >= MIN_CONTENT_CHARS


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_all_db_titles(db_path: Path) -> dict[str, dict]:
    """Return {normalized_title: {id, name, author, isbn, publisher, year, status}} for all books."""
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()
    cur.execute("""
        SELECT e.id, e.name, b.author, b.isbn, b.publisher, b.year, b.status
        FROM library_entries e JOIN library_books b ON b.id = e.entity_id
        WHERE e.type_code = 'b'
    """)
    rows = cur.fetchall()
    conn.close()
    return {
        normalize_title(r[1]): {
            "id": r[0], "name": r[1], "author": r[2] or "",
            "isbn": r[3] or "", "publisher": r[4] or "",
            "year": r[5] or "", "status": r[6] or "unread"
        }
        for r in rows
    }


def update_obsidian_link(db_path: Path, entry_id: int, link: str):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE library_entries SET obsidian_link = ?, updated_at = datetime('now') WHERE id = ?",
        (link, entry_id)
    )
    conn.commit()
    conn.close()


def get_books_missing_vault_link(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()
    cur.execute("""
        SELECT e.id, e.name, e.url, e.amazon_url,
               b.author, b.isbn, b.publisher, b.year, b.status,
               b.subtitle, b.categories, b.preview_link, b.authors
        FROM library_entries e JOIN library_books b ON b.id = e.entity_id
        WHERE e.type_code = 'b'
        AND (e.obsidian_link IS NULL OR e.obsidian_link = '')
    """)
    rows = cur.fetchall()

    # Fetch topics for each entry
    entry_ids = [r[0] for r in rows]
    topics_by_entry: dict[int, list[str]] = {}
    if entry_ids:
        ph = ",".join("?" * len(entry_ids))
        for tr in cur.execute(
            f"""SELECT jet.entry_id, lt.name
                FROM library_entry_topics jet
                JOIN library_topics lt ON jet.topic_id = lt.id
                WHERE jet.entry_id IN ({ph})""",
            entry_ids,
        ).fetchall():
            topics_by_entry.setdefault(tr[0], []).append(tr[1])

    import json as _json
    conn.close()
    return [
        {"id": r[0], "name": r[1], "url": r[2] or "", "amazon_url": r[3] or "",
         "author": r[4] or "", "isbn": r[5] or "",
         "publisher": r[6] or "", "year": r[7] or "", "status": r[8] or "unread",
         "subtitle": r[9] or "",
         "categories": _json.loads(r[10]) if r[10] else [],
         "preview_link": r[11] or "",
         "authors": _json.loads(r[12]) if r[12] else [],
         "topics": topics_by_entry.get(r[0], [])}
        for r in rows
    ]


# ── Fuzzy matching ────────────────────────────────────────────────────────────

def fuzzy_match(candidate: str, db_titles: dict, threshold: int = 60) -> tuple[str | None, float]:
    """
    Return (best_matching_norm_title, score) or (None, 0).
    Score is 0-100. threshold is minimum score to consider a match.
    """
    best_title = None
    best_score = 0

    for norm_title in db_titles:
        score = difflib.SequenceMatcher(None, candidate, norm_title).ratio() * 100
        if score > best_score:
            best_score = score
            best_title = norm_title

    if best_score >= threshold:
        return best_title, best_score
    return None, 0


# ── Main scan ─────────────────────────────────────────────────────────────────

def scan_vault(config: dict, dry_run: bool = False, db_path: Path = None) -> dict:
    """
    Scan vault. Returns result dict suitable for dry_run reporting
    and YAML generation.
    """
    vault_root    = config["vault_root"]
    books_dir     = vault_root / config["books_dir"]
    orphans_dir   = vault_root / config["orphans_dir"]
    db_path       = db_path or config["db_path"]
    high_threshold = config.get("fuzzy_match_threshold", 85)

    db_titles = get_all_db_titles(db_path)

    # ── Phase 5a: Books/ directory ────────────────────────────────────────────
    books_dir_files = list(books_dir.glob("*.md")) if books_dir.exists() else []
    # Exclude orphans subfolder files
    books_dir_files = [f for f in books_dir_files
                       if "orphans" not in str(f)]

    matched_in_books_dir = 0
    unmatched_books_dir  = []

    for md_file in books_dir_files:
        norm = title_from_path(md_file)
        if norm in db_titles:
            matched_in_books_dir += 1
            if not dry_run:
                link = f"obsidian://open?vault=MyNotes&file={md_file.relative_to(vault_root)}"
                update_obsidian_link(db_path, db_titles[norm]["id"], link)
        else:
            unmatched_books_dir.append(str(md_file.relative_to(vault_root)))

    # ── Phase 5b: Rest of vault ───────────────────────────────────────────────
    matches_list     = []
    orphans_list     = []

    # Build set of excluded top-level dirs
    exclude_dirs = {
        vault_root / d
        for d in config.get("vault_exclude_dirs", [])
    }

    all_vault_files = [
        f for f in vault_root.rglob("*.md")
        if books_dir not in f.parents
        and orphans_dir not in f.parents
        and not any(excl in f.parents or f.parent == excl for excl in exclude_dirs)
        and f.suffix == ".md"
    ]

    for md_file in all_vault_files:
        body = extract_body(md_file)
        fm   = extract_frontmatter(md_file)

        # Try to get title from frontmatter, fallback to filename
        fm_title = fm.get("title", "")
        if isinstance(fm_title, list):
            fm_title = fm_title[0] if fm_title else ""
        fm_title = str(fm_title) if fm_title else ""
        candidate = normalize_title(fm_title) if fm_title else title_from_path(md_file)

        # Skip utility files with very short titles
        if len(candidate) < 5:
            continue

        content_chars = len(body)

        if content_chars < MIN_CONTENT_CHARS:
            # Empty stub — orphan candidate
            matched_title, score = fuzzy_match(candidate, db_titles, threshold=70)
            if matched_title:
                orphans_list.append({
                    "action": "move_orphan",
                    "src_path": str(md_file.relative_to(vault_root)),
                    "dest_path": str(config["orphans_dir"] / md_file.name),
                    "content_chars": content_chars,
                })
            continue

        # Has content — try to match (raised from 60 → 80)
        matched_title, score = fuzzy_match(candidate, db_titles, threshold=80)
        if not matched_title:
            continue

        db_entry = db_titles[matched_title]
        confidence = "high" if score >= high_threshold else "review"
        dest_path  = str(config["books_dir"]) + "/" + _safe_filename(db_entry["name"])

        matches_list.append({
            "action": "move",
            "confidence": confidence,
            "src_path": str(md_file.relative_to(vault_root)),
            "dest_path": dest_path,
            "db_title": db_entry["name"],
            "db_author": db_entry["author"],
            "content_chars": content_chars,
            "_entry_id": db_entry["id"],  # used by apply, stripped from YAML
        })

    # ── Stubs needed ──────────────────────────────────────────────────────────
    stubs_needed = len(get_books_missing_vault_link(db_path)) if not dry_run else \
                   len(db_titles) - matched_in_books_dir - len(matches_list)

    high_confidence = sum(1 for m in matches_list if m["confidence"] == "high")
    needs_review    = sum(1 for m in matches_list if m["confidence"] == "review")

    return {
        "books_dir_count":       len(books_dir_files),
        "matched":               matched_in_books_dir,
        "unmatched_books_dir":   len(unmatched_books_dir),
        "outside_with_content":  len(matches_list),
        "high_confidence":       high_confidence,
        "needs_review":          needs_review,
        "orphans":               len(orphans_list),
        "stubs_needed":          stubs_needed,
        "review_entries":        len(matches_list) + len(orphans_list),
        "matches":               matches_list,
        "orphans_list":          orphans_list,
        "unmatched_books_dir_list": unmatched_books_dir,
    }


# ── Apply review YAML ─────────────────────────────────────────────────────────

def apply_vault_yaml(yaml_path: Path, config: dict, db_path: Path = None):
    """Execute approved moves from the review YAML."""
    db_path    = db_path or config["db_path"]
    vault_root = config["vault_root"]
    db_titles  = get_all_db_titles(db_path)

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    moves_done   = 0
    orphans_done = 0
    skipped      = 0
    errors       = []

    for entry in data.get("matches", []):
        if entry.get("action") == "skip":
            skipped += 1
            continue
        src  = vault_root / entry["src_path"]
        dest = vault_root / entry["dest_path"]
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            # Update DB link
            norm = normalize_title(entry.get("db_title", dest.stem))
            if norm in db_titles:
                link = f"obsidian://open?vault=MyNotes&file={entry['dest_path']}"
                update_obsidian_link(db_path, db_titles[norm]["id"], link)
            moves_done += 1
        except Exception as e:
            errors.append(f"Move failed {src} → {dest}: {e}")

    for entry in data.get("orphans", []):
        if entry.get("action") == "skip":
            skipped += 1
            continue
        src  = vault_root / entry["src_path"]
        dest = vault_root / entry["dest_path"]
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            orphans_done += 1
        except Exception as e:
            errors.append(f"Orphan move failed {src} → {dest}: {e}")

    print(f"  Moves completed:   {moves_done}")
    print(f"  Orphans moved:     {orphans_done}")
    print(f"  Skipped:           {skipped}")
    if errors:
        print(f"  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    {e}")


# ── Create stubs ──────────────────────────────────────────────────────────────

def create_stubs(config: dict, db_path: Path = None) -> int:
    """Create stub .md files for all books missing an obsidian_link."""
    db_path    = db_path or config["db_path"]
    vault_root = config["vault_root"]
    books_dir  = vault_root / config["books_dir"]
    books_dir.mkdir(parents=True, exist_ok=True)

    books = get_books_missing_vault_link(db_path)
    today = str(date.today())
    created = 0

    for book in books:
        filename = _safe_filename(book["name"])
        dest = books_dir / filename
        if dest.exists():
            # File appeared since last scan — just link it
            link = f"obsidian://open?vault=MyNotes&file={dest.relative_to(vault_root)}"
            update_obsidian_link(db_path, book["id"], link)
            continue

        content = STUB_TEMPLATE.format(
            title        = book["name"],
            author       = book["author"],
            subtitle     = book.get("subtitle") or "",
            authors      = ", ".join(book.get("authors") or []),
            publisher    = book["publisher"] or "",
            year         = book["year"] or "",
            isbn         = book["isbn"] or "",
            categories   = ", ".join(book.get("categories") or []),
            status       = book["status"],
            url          = book.get("url") or "",
            amazon_url   = book.get("amazon_url") or "",
            preview_link = book.get("preview_link") or "",
            topics       = ", ".join(book.get("topics") or []),
            created_at   = today,
            updated_at   = today,
        )
        dest.write_text(content, encoding="utf-8")
        link = f"obsidian://open?vault=MyNotes&file={dest.relative_to(vault_root)}"
        update_obsidian_link(db_path, book["id"], link)
        created += 1

    return created


def _safe_filename(title: str) -> str:
    """Convert title to a safe .md filename."""
    # Strip subtitle
    title = title.split(":")[0].strip()
    # Remove characters not safe in filenames
    title = re.sub(r'[<>:"/\\|?*]', "", title)
    return title + ".md"
