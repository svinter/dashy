"""
Backfill obsidian_link for non-book library entries missing vault links.

Two passes:
  1. MATCH  — articles, essays, research, notes, courses: fuzzy-match entry
             name against existing vault .md filenames and update obsidian_link.
  2. STUBS  — tools (t) and worksheets (s): create stub .md files in
             4 Library/Tools/ and set obsidian_link.

Quotes (q) are skipped — no vault folder exists for them.

Usage:
    python scripts/backfill_vault_links.py [--dry-run]
"""
import argparse
import json
import re
import sqlite3
import unicodedata
from datetime import date
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
VAULT_ROOT   = Path.home() / "Obsidian/MyNotes"
LIBRARY_ROOT = VAULT_ROOT / "4 Library"
STUB_FOLDER  = LIBRARY_ROOT / "Tools"
DB_PATH      = Path.home() / ".personal-dashboard/dashboard.db"

# ---------------------------------------------------------------------------
# Type → preferred search folders (searched recursively)
# ---------------------------------------------------------------------------
TYPE_SEARCH_FOLDERS: dict[str, list[str]] = {
    'a': ['Articles', 'HBR'],
    'e': ['Essays', 'Exploring'],
    'r': ['Papers', 'Coaching Papers', 'Mgmt Papers', 'Google overflow'],
    'n': ['Notes', 'Walkabout'],
    'c': ['Courses'],
}

MATCHABLE_TYPES = set(TYPE_SEARCH_FOLDERS.keys())
STUB_TYPES      = {'t', 's'}

GDOC_ID_RE = re.compile(r'/d/([a-zA-Z0-9_\-]{20,})')

TODAY = date.today().isoformat()


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Lowercase, strip accents, collapse separators and whitespace."""
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = text.lower()
    text = re.sub(r'[/\\\-_:]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# ---------------------------------------------------------------------------
# Build vault index
# ---------------------------------------------------------------------------

def build_vault_index(type_code: str) -> dict[str, Path]:
    """
    Return {normalized_stem: absolute_path} for all .md files found in
    the preferred folders for this type.  Searches recursively.
    Falls back to searching all of 4 Library/ if a folder doesn't exist.
    """
    folders = TYPE_SEARCH_FOLDERS.get(type_code, [])
    paths: list[Path] = []
    for folder_name in folders:
        folder = LIBRARY_ROOT / folder_name
        if folder.exists():
            paths.extend(folder.rglob('*.md'))

    # If no dedicated folders found (shouldn't happen), search full library
    if not paths:
        paths = list(LIBRARY_ROOT.rglob('*.md'))

    index: dict[str, Path] = {}
    for p in paths:
        key = normalize(p.stem)
        # Prefer shorter/shallower path on collision
        if key not in index or len(str(p)) < len(str(index[key])):
            index[key] = p
    return index


# ---------------------------------------------------------------------------
# Build obsidian:// link from absolute path
# ---------------------------------------------------------------------------

def make_obsidian_link(abs_path: Path) -> str:
    rel = abs_path.relative_to(VAULT_ROOT)
    return f"obsidian://open?vault=MyNotes&file={rel}"


# ---------------------------------------------------------------------------
# Match one entry against the index
# ---------------------------------------------------------------------------

def match_entry(name: str, index: dict[str, Path]) -> tuple[Path | None, str]:
    """Return (matched_path, method) or (None, 'no_match')."""
    key = normalize(name)

    # 1. Exact
    if key in index:
        return index[key], 'exact'

    # 2. Fuzzy — best match above threshold
    candidates = list(index.keys())
    close = get_close_matches(key, candidates, n=1, cutoff=0.85)
    if close:
        return index[close[0]], f'fuzzy({close[0]!r})'

    return None, 'no_match'


# ---------------------------------------------------------------------------
# Stub creation for tools / worksheets
# ---------------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    """Convert entry name to a safe filename stem."""
    name = re.sub(r'[/\\:*?"<>|]', '-', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def extract_gdoc_id(url: str | None) -> str | None:
    if not url:
        return None
    m = GDOC_ID_RE.search(url)
    return m.group(1) if m else None


def build_stub_content(entry_id: int, name: str, type_code: str,
                        url: str | None) -> str:
    gdoc_id = extract_gdoc_id(url)
    type_label = 'Tool' if type_code == 't' else 'Worksheet'
    lines = [
        '---',
        f'title: "{name}"',
        f'type: {type_label.lower()}',
    ]
    if url:
        lines.append(f'url: "{url}"')
    if gdoc_id:
        lines.append(f'gdoc_id: "{gdoc_id}"')
    lines += [
        f'created: {TODAY}',
        '---',
        '',
        f'# {name}',
        '',
    ]
    if url:
        lines.append(f'[Open {type_label}]({url})')
        lines.append('')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    dry = args.dry_run
    mode = 'DRY RUN' if dry else 'LIVE'
    print(f"=== backfill_vault_links — {mode} ===\n")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    rows = db.execute(
        """
        SELECT id, name, type_code, url
        FROM library_entries
        WHERE (obsidian_link IS NULL OR obsidian_link = '')
          AND type_code IN ('a','e','r','n','c','t','s')
        ORDER BY type_code, name
        """
    ).fetchall()

    # Group by type
    by_type: dict[str, list] = {}
    for row in rows:
        by_type.setdefault(row['type_code'], []).append(row)

    # -----------------------------------------------------------------------
    # Pass 1: match existing vault files
    # -----------------------------------------------------------------------
    print("── Pass 1: Matching against vault files ──\n")
    match_stats: dict[str, dict] = {}

    for tc in sorted(MATCHABLE_TYPES):
        entries = by_type.get(tc, [])
        if not entries:
            match_stats[tc] = {'total': 0, 'exact': 0, 'fuzzy': 0, 'miss': 0}
            continue

        index = build_vault_index(tc)
        stats = {'total': len(entries), 'exact': 0, 'fuzzy': 0, 'miss': 0}

        for entry in entries:
            path, method = match_entry(entry['name'], index)
            if path:
                link = make_obsidian_link(path)
                if 'exact' in method:
                    stats['exact'] += 1
                else:
                    stats['fuzzy'] += 1
                    print(f"  [{tc}] fuzzy  {entry['name']!r}")
                    print(f"        → {path.name!r}")
                if not dry:
                    db.execute(
                        "UPDATE library_entries SET obsidian_link = ? WHERE id = ?",
                        (link, entry['id']),
                    )
            else:
                stats['miss'] += 1
                print(f"  [{tc}] MISS   {entry['name']!r}")

        match_stats[tc] = stats
        print(f"  [{tc}] total={stats['total']}  exact={stats['exact']}  "
              f"fuzzy={stats['fuzzy']}  miss={stats['miss']}")
        print()

    # -----------------------------------------------------------------------
    # Pass 2: stubs for tools and worksheets
    # -----------------------------------------------------------------------
    print("── Pass 2: Creating stubs for tools and worksheets ──\n")
    stub_stats: dict[str, dict] = {}

    if not dry and not STUB_FOLDER.exists():
        STUB_FOLDER.mkdir(parents=True)
        print(f"  Created folder: {STUB_FOLDER}\n")
    elif dry and not STUB_FOLDER.exists():
        print(f"  Would create folder: {STUB_FOLDER}\n")

    for tc in ('t', 's'):
        entries = by_type.get(tc, [])
        stats = {'total': len(entries), 'created': 0, 'collision': 0}

        for entry in entries:
            stem = sanitize_filename(entry['name'])
            stub_path = STUB_FOLDER / f"{stem}.md"

            # Handle filename collisions
            if stub_path.exists() and not dry:
                stub_path = STUB_FOLDER / f"{stem}-{entry['id']}.md"
                stats['collision'] += 1

            content = build_stub_content(
                entry['id'], entry['name'], tc, entry['url']
            )
            link = make_obsidian_link(stub_path)

            if dry:
                print(f"  [{tc}] would create  {stub_path.name}")
            else:
                stub_path.write_text(content, encoding='utf-8')
                db.execute(
                    "UPDATE library_entries SET obsidian_link = ? WHERE id = ?",
                    (link, entry['id']),
                )
                stats['created'] += 1

        stub_stats[tc] = stats
        action = 'would create' if dry else 'created'
        print(f"  [{tc}] total={stats['total']}  {action}={stats['total'] if dry else stats['created']}")
        print()

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    if not dry:
        db.commit()

    db.close()

    print("═" * 56)
    print("SUMMARY")
    print("═" * 56)
    type_names = {'a': 'Article', 'e': 'Essay', 'r': 'Research',
                  'n': 'Note', 'c': 'Course', 't': 'Tool', 's': 'Worksheet'}
    for tc, stats in {**match_stats, **stub_stats}.items():
        label = type_names.get(tc, tc)
        if 'exact' in stats:
            matched = stats['exact'] + stats['fuzzy']
            print(f"  {label:12s}  {stats['total']:3d} entries  "
                  f"{matched:3d} matched  {stats['miss']:3d} unresolved")
        else:
            action = 'would stub' if dry else 'stubbed'
            print(f"  {label:12s}  {stats['total']:3d} entries  "
                  f"{stats['total']:3d} {action}")

    if dry:
        total_match = sum(
            s['exact'] + s['fuzzy'] for s in match_stats.values()
        )
        total_miss = sum(s['miss'] for s in match_stats.values())
        total_stubs = sum(s['total'] for s in stub_stats.values())
        print(f"\n  Match pass:  {total_match} linked, {total_miss} unresolved")
        print(f"  Stub pass:   {total_stubs} stubs would be created")
        print(f"\n  Run without --dry-run to apply.")


if __name__ == '__main__':
    main()
