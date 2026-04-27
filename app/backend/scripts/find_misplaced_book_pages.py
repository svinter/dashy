#!/usr/bin/env python3
"""Search entire vault for 783 books missing obsidian_link.

Flags:
  --dry-run          (default) show matches, no moves or DB updates
  --apply-confident  move + update DB for score >= 85
  --apply-all        move + update DB for all matches (>=65)
"""

import argparse
import csv
import re
import shutil
import sqlite3
from pathlib import Path

from rapidfuzz import fuzz

VAULT_ROOT = Path("/Users/stevevinter/Obsidian/MyNotes")
BOOKS_FOLDER = VAULT_ROOT / "4 Library/Books"
DB_PATH = Path.home() / ".personal-dashboard/dashboard.db"
DESKTOP = Path.home() / "Desktop"

SKIP_FOLDERS = {
    # Already audited
    "4 Library/Books",
    "4 Library/Highlights",
    "4 Library/Summaries",
    # Not book pages
    "8 Meetings",
    ".obsidian",
    "9 Daily",           # daily journal entries
    "1 People",          # people/contact notes
    "2 Coaching",        # coaching session notes
    "3 Areas",           # areas of life notes
    "7 Miscellaneous",   # misc writing/snippets
    "4 Library/The Book", # Steve's own writing project
    "Projects",
    "0 Home",
    "Templates",
}

HIGH_CONF = 85
NEEDS_REVIEW = 65


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    s = s.lower()
    # Strip subtitle after colon
    colon = s.find(":")
    if colon > 0:
        s = s[:colon]
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _obsidian_link(rel_path: str) -> str:
    return f"obsidian://open?vault=MyNotes&file={rel_path}"


def _is_skipped(path: Path) -> bool:
    rel = path.relative_to(VAULT_ROOT)
    parts = rel.parts
    for skip in SKIP_FOLDERS:
        skip_parts = tuple(skip.split("/"))
        if parts[:len(skip_parts)] == skip_parts:
            return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply-confident", action="store_true")
    parser.add_argument("--apply-all", action="store_true")
    parser.add_argument("--min-score", type=float, default=None,
                        help="Override minimum score threshold for apply (e.g. 99)")
    args = parser.parse_args()

    if args.apply_all or args.apply_confident:
        args.dry_run = False

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Load missing books
    books = conn.execute("""
        SELECT e.id, e.name
        FROM library_entries e
        WHERE e.type_code = 'b'
          AND (e.obsidian_link IS NULL OR e.obsidian_link = '')
        ORDER BY e.name
    """).fetchall()

    print(f"Loaded {len(books)} books missing obsidian_link")

    # Scan vault (excluding skip folders)
    print("Scanning vault...")
    vault_files: list[Path] = []
    for p in VAULT_ROOT.rglob("*.md"):
        if not _is_skipped(p):
            vault_files.append(p)

    print(f"Found {len(vault_files):,} vault .md files (outside skip folders)")
    print()

    # Pre-normalise vault stems; drop stems < 4 chars (noise)
    vault_norm: list[tuple[str, Path]] = [
        (_normalize(p.stem), p) for p in vault_files
        if len(p.stem.strip()) >= 4
    ]

    # Match each book
    high: list[dict] = []
    review: list[dict] = []
    no_match: list[dict] = []

    for book in books:
        norm = _normalize(book["name"])
        norm_words = norm.split()
        best_score = 0
        best_path: Path | None = None
        for vn, vp in vault_norm:
            vn_words = vn.split()
            # Length guard: vault stem word count must be within 2× of the
            # book title's word count (bidirectional).  Prevents short filenames
            # like "Power.md" from matching a 10-word title.
            book_wc = max(1, len(norm_words))
            vault_wc = max(1, len(vn_words))
            if min(book_wc, vault_wc) / max(book_wc, vault_wc) < 0.4:
                continue
            # Plain edit-distance ratio — no partial/subset matching.
            # High scores here mean the strings are genuinely similar as a whole.
            score = fuzz.ratio(norm, vn)
            if score > best_score:
                best_score = score
                best_path = vp

        entry = {
            "id": book["id"],
            "name": book["name"],
            "score": best_score,
            "source": best_path,
            "dest": BOOKS_FOLDER / best_path.name if best_path else None,
        }

        if best_score >= HIGH_CONF:
            high.append(entry)
        elif best_score >= NEEDS_REVIEW:
            review.append(entry)
        else:
            no_match.append(entry)

    # ---------------------------------------------------------------------------
    # Print report
    # ---------------------------------------------------------------------------
    def _rel(p: Path | None) -> str:
        if p is None:
            return "?"
        return str(p.relative_to(VAULT_ROOT))

    print("Misplaced Book Page Search")
    print("==========================")
    print()

    print(f"HIGH CONFIDENCE (≥{HIGH_CONF}): {len(high)}")
    for e in high:
        dest_exists = e["dest"].exists() if e["dest"] else False
        note = " [DEST EXISTS — would skip]" if dest_exists else ""
        print(f'  "{e["name"]}"')
        print(f'    → Found: {_rel(e["source"])} (score={e["score"]}){note}')
        print(f'    → Would move to: 4 Library/Books/{e["dest"].name if e["dest"] else "?"}')
    print()

    print(f"NEEDS REVIEW ({NEEDS_REVIEW}–{HIGH_CONF-1}): {len(review)}")
    for e in review:
        dest_exists = e["dest"].exists() if e["dest"] else False
        note = " [DEST EXISTS — would skip]" if dest_exists else ""
        print(f'  "{e["name"]}"')
        print(f'    → Found: {_rel(e["source"])} (score={e["score"]}){note}')
        print(f'    → Would move to: 4 Library/Books/{e["dest"].name if e["dest"] else "?"}')
    print()

    print(f"NO MATCH (<{NEEDS_REVIEW}): {len(no_match)}")
    for e in no_match:
        print(f'  "{e["name"]}" — best score {e["score"]} ({_rel(e["source"])})')
    print()

    print("TOTALS:")
    print(f"  High confidence: {len(high):>4}")
    print(f"  Needs review:    {len(review):>4}")
    print(f"  No match:        {len(no_match):>4}  (need stub creation)")
    print()

    # ---------------------------------------------------------------------------
    # Apply
    # ---------------------------------------------------------------------------
    if args.apply_all:
        to_apply = high + review
    elif args.apply_confident:
        to_apply = high
    else:
        to_apply = []

    if args.min_score is not None and to_apply:
        before = len(to_apply)
        to_apply = [e for e in to_apply if e["score"] >= args.min_score]
        print(f"--min-score {args.min_score}: filtered {before} → {len(to_apply)} entries")

    if to_apply:
        print(f"Applying {len(to_apply)} moves...")
        moved = 0
        skipped_dest = 0
        db_updated = 0
        for e in to_apply:
            src = e["source"]
            dest = e["dest"]
            if dest is None:
                continue
            if dest.exists():
                print(f"  SKIP (dest exists): {dest.name}")
                skipped_dest += 1
            else:
                shutil.move(str(src), str(dest))
                print(f"  MOVED: {_rel(src)} → 4 Library/Books/{dest.name}")
                moved += 1
            rel_link = f"4 Library/Books/{dest.name}"
            link = _obsidian_link(rel_link)
            conn.execute(
                "UPDATE library_entries SET obsidian_link = ?, updated_at = datetime('now') WHERE id = ?",
                (link, e["id"]),
            )
            db_updated += 1
        conn.commit()
        print(f"  Moved: {moved}, Skipped (dest exists): {skipped_dest}, DB updated: {db_updated}")

    conn.close()

    # ---------------------------------------------------------------------------
    # CSVs
    # ---------------------------------------------------------------------------
    conf_csv = DESKTOP / "misplaced_books_confident.csv"
    with open(conf_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "score", "source_path", "dest_name"])
        w.writeheader()
        for e in high:
            w.writerow({"id": e["id"], "name": e["name"], "score": e["score"],
                        "source_path": _rel(e["source"]), "dest_name": e["dest"].name if e["dest"] else ""})

    review_csv = DESKTOP / "misplaced_books_review.csv"
    with open(review_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "score", "source_path", "dest_name"])
        w.writeheader()
        for e in review:
            w.writerow({"id": e["id"], "name": e["name"], "score": e["score"],
                        "source_path": _rel(e["source"]), "dest_name": e["dest"].name if e["dest"] else ""})

    no_match_csv = DESKTOP / "books_no_match.csv"
    with open(no_match_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "best_score", "best_match_path"])
        w.writeheader()
        for e in no_match:
            w.writerow({"id": e["id"], "name": e["name"], "best_score": e["score"],
                        "best_match_path": _rel(e["source"])})

    print(f"Written: {conf_csv}  ({len(high)} rows)")
    print(f"Written: {review_csv}  ({len(review)} rows)")
    print(f"Written: {no_match_csv}  ({len(no_match)} rows)")


if __name__ == "__main__":
    main()
