#!/usr/bin/env python3
"""Vault ↔ Library reconciliation audit.

Produces a console report + two CSVs on the Desktop.
"""

import csv
import re
import sqlite3
from pathlib import Path
from urllib.parse import unquote

from rapidfuzz import fuzz

VAULT_ROOT = Path("/Users/stevevinter/Obsidian/MyNotes")
DB_PATH = Path.home() / ".personal-dashboard/dashboard.db"
DESKTOP = Path.home() / "Desktop"

VAULT_FOLDERS: dict[str, list[str]] = {
    'b': ['4 Library/Books'],
    'a': ['4 Library/Articles', '4 Library/HBR'],
    'e': ['4 Library/Essays', '4 Library/Exploring'],
    'r': ['4 Library/Papers', '4 Library/Coaching Papers',
          '4 Library/Mgmt Papers', '4 Library/Google overflow'],
    't': ['4 Library/Tools', '4 Library/Coaching/Tools'],
    's': ['4 Library/Tools/Templates',
          '4 Library/Coaching/Assessments/Reflection Exercises'],
    'n': ['4 Library/Notes', '4 Library/Walkabout'],
    'p': ['4 Library/Podcasts'],
    'c': ['4 Library/Courses'],
    'z': ['4 Library/Coaching/Assessments'],
}

TYPE_LABELS = {
    'a': 'Articles',
    'b': 'Books',
    'c': 'Courses',
    'e': 'Essays',
    'n': 'Notes',
    'p': 'Podcasts',
    'r': 'Papers',
    's': 'Exercises/Templates',
    't': 'Tools',
    'z': 'Assessments',
}

FUZZY_ORPHAN_THRESHOLD = 70  # score below this → vault orphan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _obsidian_link_to_path(link: str) -> Path | None:
    """Convert obsidian://open?vault=MyNotes&file=... → absolute Path."""
    m = re.search(r'[?&]file=([^&]+)', link)
    if not m:
        return None
    rel = unquote(m.group(1))
    return VAULT_ROOT / rel


def _scan_vault_files(folders: list[str]) -> dict[str, Path]:
    """Return {stem: path} for all .md files in the given vault folders."""
    files: dict[str, Path] = {}
    for folder in folders:
        d = VAULT_ROOT / folder
        if not d.exists():
            continue
        for p in d.rglob("*.md"):
            files[p.stem] = p
    return files


def _normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    missing_rows: list[dict] = []
    orphan_rows: list[dict] = []

    type_stats: list[dict] = []

    for tc, folders in VAULT_FOLDERS.items():
        vault_files = _scan_vault_files(folders)  # stem → Path
        vault_norms = {_normalize(stem): stem for stem in vault_files}

        entries = conn.execute(
            "SELECT id, name, type_code, url, obsidian_link "
            "FROM library_entries WHERE type_code = ? ORDER BY name",
            (tc,),
        ).fetchall()

        n_entries = len(entries)
        n_with_link = sum(1 for e in entries if e["obsidian_link"])
        n_matched = 0
        n_missing = 0

        # Track vault stems matched to a library entry
        matched_vault_stems: set[str] = set()

        for e in entries:
            link = e["obsidian_link"]
            if link:
                vault_path = _obsidian_link_to_path(link)
                if vault_path and vault_path.exists():
                    n_matched += 1
                    matched_vault_stems.add(vault_path.stem)
                    continue
            # No link or file missing
            n_missing += 1
            missing_rows.append({
                "id": e["id"],
                "name": e["name"],
                "type": tc,
                "url": e["url"] or "",
            })

        # Vault orphans: vault files not matched to any library entry
        unmatched_vault_stems = set(vault_files.keys()) - matched_vault_stems
        for stem in sorted(unmatched_vault_stems):
            norm = _normalize(stem)
            best_score = 0
            best_name = ""
            for e in entries:
                score = fuzz.token_set_ratio(norm, _normalize(e["name"]))
                if score > best_score:
                    best_score = score
                    best_name = e["name"]
            if best_score < FUZZY_ORPHAN_THRESHOLD:
                orphan_rows.append({
                    "path": str(vault_files[stem].relative_to(VAULT_ROOT)),
                    "type": tc,
                    "fuzzy_best_match": best_name,
                    "score": best_score,
                })

        n_vault_total = len(vault_files)
        n_orphans = sum(1 for o in orphan_rows if o["type"] == tc)

        type_stats.append({
            "tc": tc,
            "label": TYPE_LABELS.get(tc, tc),
            "n_entries": n_entries,
            "n_with_link": n_with_link,
            "n_missing": n_missing,
            "n_vault_total": n_vault_total,
            "n_orphans": n_orphans,
        })

    conn.close()

    # ---------------------------------------------------------------------------
    # Print report
    # ---------------------------------------------------------------------------
    print("Vault ↔ Library Audit")
    print("=====================")
    print()

    total_entries = 0
    total_matched = 0
    total_missing = 0
    total_orphans = 0

    for s in type_stats:
        matched = s["n_with_link"] - s["n_missing"]  # linked AND file exists
        # Recalculate matched more precisely from missing
        actual_missing = s["n_missing"]
        actual_matched = s["n_entries"] - actual_missing

        print(f"{s['label']} ({s['tc']})")
        print(f"  Library entries:    {s['n_entries']:>6,}")
        print(f"  With obsidian_link: {s['n_with_link']:>6,}")
        print(f"  Missing vault page: {actual_missing:>6,}  (link null or file not found)")
        print(f"  Vault files total:  {s['n_vault_total']:>6,}")
        print(f"  Vault orphans:      {s['n_orphans']:>6,}  (in vault, not in library)")
        print()

        total_entries += s["n_entries"]
        total_matched += actual_matched
        total_missing += actual_missing
        total_orphans += s["n_orphans"]

    print("SUMMARY")
    print("=======")
    print(f"Total library entries:   {total_entries:>6,}")
    print(f"Matched (both sides):    {total_matched:>6,}")
    print(f"Missing vault page:      {total_missing:>6,}")
    print(f"Vault orphans:           {total_orphans:>6,}")
    print()

    # ---------------------------------------------------------------------------
    # Write CSVs
    # ---------------------------------------------------------------------------
    missing_csv = DESKTOP / "missing_vault_pages.csv"
    with open(missing_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "type", "url"])
        w.writeheader()
        w.writerows(missing_rows)
    print(f"Written: {missing_csv}  ({len(missing_rows):,} rows)")

    orphan_csv = DESKTOP / "vault_orphans.csv"
    with open(orphan_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["path", "type", "fuzzy_best_match", "score"])
        w.writeheader()
        w.writerows(orphan_rows)
    print(f"Written: {orphan_csv}  ({len(orphan_rows):,} rows)")


if __name__ == "__main__":
    main()
