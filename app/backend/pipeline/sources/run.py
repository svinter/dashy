#!/usr/bin/env python3
"""
libby_pipeline/run.py — Libby Data Import Pipeline
Version 1.0

Usage:
  python run.py --dry-run           # counts only, no writes
  python run.py --load              # parse + dedup + load to DB
  python run.py --resolve-urls      # resolve tinyurls → amazon_url
  python run.py --enrich            # Google Books API enrichment
  python run.py --vault-scan        # scan vault, generate review YAML
  python run.py --vault-apply FILE  # execute approved review YAML
  python run.py --create-stubs      # create stub .md files for unmatched books

Flags may be combined except --dry-run (suppresses all writes globally).
"""

import argparse
import sys
from pathlib import Path

# Pipeline modules
from parse import parse_all_sources
from dedup import dedup_and_merge
from enrich import resolve_urls, enrich_google_books
from vault import scan_vault, apply_vault_yaml, create_stubs
from db import init_db, load_to_db
from report import dry_run_report

# ── Config ────────────────────────────────────────────────────────────────────

def _load_install_config() -> dict:
    """Load dashy_install.json from the repo root; return {} on any error."""
    try:
        import json
        repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        cfg_path = repo_root / "dashy_install.json"
        if cfg_path.exists():
            return json.loads(cfg_path.read_text())
    except Exception:
        pass
    return {}


_install = _load_install_config()
_vault_root = Path(_install.get("obsidian", {}).get("vault_path", "/Users/stevevinter/Obsidian/MyNotes"))
_lib_folder = _install.get("obsidian", {}).get("folders", {}).get("library", "4 Library")

CONFIG = {
    # Source files (resolved relative to this file's directory)
    "ground_truth":  Path(__file__).parent / "ground_truth.txt",
    "curated_md":    Path(__file__).parent / "Curated.md",
    "favorites_md":  Path(__file__).parent / "Favorites.md",
    "summaries_md":  Path(__file__).parent / "Summaries.md",
    "gbooks_pdf":    Path(__file__).parent / "Your_library.pdf",

    # Vault
    "vault_root":    _vault_root,
    "books_dir":     Path(f"{_lib_folder}/Books"),
    "highlights_dir":Path(f"{_lib_folder}/Highlights"),
    "summaries_dir": Path(f"{_lib_folder}/Summaries"),
    "orphans_dir":   Path(f"{_lib_folder}/Books/orphans"),

    # DB
    "db_path":       Path("/Users/stevevinter/.personal-dashboard/dashboard.db"),

    # Output
    "review_yaml":   Path("reconciliation.yaml"),

    # Tuning
    "min_content_chars": 200,       # below this = empty stub
    "fuzzy_match_threshold": 85,    # 0-100, confidence cutoff for high vs review

    # Vault folders to exclude from outside-Books/ scan
    "vault_exclude_dirs": [
        "1 Company", "1 People", "2 Projects", "3 Areas",
        "6 Admin", "7 Miscellaneous", "8 Meetings", "Inbox",
        "Templates", "Daily Notes", "Journal",
    ],
}

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Libby data import pipeline")
    parser.add_argument("--dry-run",       action="store_true", help="Counts only, no writes")
    parser.add_argument("--load",          action="store_true", help="Parse + dedup + load to DB")
    parser.add_argument("--resolve-urls",  action="store_true", help="Resolve tinyurls")
    parser.add_argument("--enrich",        action="store_true", help="Google Books API enrichment")
    parser.add_argument("--vault-scan",    action="store_true", help="Scan vault, generate review YAML")
    parser.add_argument("--vault-apply",   metavar="FILE",      help="Execute approved review YAML")
    parser.add_argument("--create-stubs",  action="store_true", help="Create stub vault .md files")
    parser.add_argument("--all",           action="store_true", help="Run full pipeline (except vault-apply)")
    parser.add_argument("--limit",         type=int, default=None, help="Max books to enrich in this run")
    args = parser.parse_args()

    dry = args.dry_run

    if dry:
        print("=" * 53)
        print("Libby Pipeline Dry Run")
        print("=" * 53)

    if not any(vars(args).values()):
        parser.print_help()
        sys.exit(0)

    # ── Parse + Load ──────────────────────────────────────────────────────────
    if args.load or args.all or dry:
        print("\n[1/5] Parsing sources...")
        staging = parse_all_sources(CONFIG)

        print("\n[2/5] Deduplicating and merging...")
        merged = dedup_and_merge(staging)

        if dry:
            dry_run_report(staging, merged)
        else:
            print("\n[3/5] Loading to database...")
            init_db(CONFIG["db_path"])
            load_to_db(merged, CONFIG["db_path"])
            print(f"  Loaded {len(merged['books'])} books")
            print(f"  Loaded {len(merged['unresolved'])} unresolved entries")

    # ── URL Resolution ────────────────────────────────────────────────────────
    if args.resolve_urls or args.all:
        print("\n[URL Resolution] Resolving tinyurls → Amazon URLs...")
        if dry:
            print("  DRY RUN: would resolve ~1,095 URLs (estimated ~18 min)")
        else:
            resolve_urls(CONFIG["db_path"])

    # ── API Enrichment ────────────────────────────────────────────────────────
    if args.enrich or args.all:
        print("\n[Enrichment] Google Books API...")
        if dry:
            print("  DRY RUN: would enrich books with needs_enrichment=1")
        else:
            enrich_google_books(CONFIG["db_path"], limit=args.limit)

    # ── Vault Scan ────────────────────────────────────────────────────────────
    if args.vault_scan or args.all or dry:
        print("\n[Vault] Scanning vault...")
        results = scan_vault(CONFIG, dry_run=dry)
        if dry:
            _print_vault_summary(results)
        else:
            _write_review_yaml(results, CONFIG["review_yaml"])
            print(f"  Review YAML written to: {CONFIG['review_yaml']}")
            print(f"  Edit the file, then run: python run.py --vault-apply {CONFIG['review_yaml']}")

    # ── Vault Apply ───────────────────────────────────────────────────────────
    if args.vault_apply:
        yaml_path = Path(args.vault_apply)
        if not yaml_path.exists():
            print(f"ERROR: review file not found: {yaml_path}")
            sys.exit(1)
        print(f"\n[Vault] Applying review YAML: {yaml_path}")
        if dry:
            print("  DRY RUN: would apply approved moves and orphan moves")
        else:
            apply_vault_yaml(yaml_path, CONFIG)

    # ── Create Stubs ──────────────────────────────────────────────────────────
    if args.create_stubs:
        print("\n[Vault] Creating stub .md files for unmatched books...")
        if dry:
            print("  DRY RUN: would create stubs (count shown in vault summary above)")
        else:
            n = create_stubs(CONFIG)
            print(f"  Created {n} stub files in {CONFIG['vault_root'] / CONFIG['books_dir']}")

    if dry:
        print("\n" + "=" * 53)
        print("Dry run complete. No files or DB were modified.")
        print("=" * 53)


def _print_vault_summary(results: dict):
    print(f"  Books/ files found:               {results['books_dir_count']:>6}")
    print(f"  Matched to DB:                    {results['matched']:>6}")
    print(f"  Unmatched Books/ files:           {results['unmatched_books_dir']:>6}")
    print(f"  Outside Books/ with content:      {results['outside_with_content']:>6}")
    print(f"    High confidence matches:        {results['high_confidence']:>6}")
    print(f"    Needs review:                   {results['needs_review']:>6}")
    print(f"  Outside Books/ empty (orphans):   {results['orphans']:>6}")
    print(f"  DB entries with no vault file:    {results['stubs_needed']:>6}  (--create-stubs)")
    print(f"\n  Review YAML would contain:        {results['review_entries']:>6} entries")


def _write_review_yaml(results: dict, path: Path):
    """Write the reconciliation review YAML file."""
    import yaml
    with open(path, "w") as f:
        f.write("# Libby Vault Reconciliation Review\n")
        f.write(f"# Generated: {__import__('datetime').date.today()}\n")
        f.write("#\n")
        f.write("# Instructions:\n")
        f.write("#   DELETE an entry block to skip that action entirely\n")
        f.write("#   Change action: move → action: skip to defer\n")
        f.write("#   Edit dest_path to rename during move\n")
        f.write("#   Save and upload when done\n")
        f.write("#\n")
        f.write(f"# Stubs: {results['stubs_needed']} books have no vault file.\n")
        f.write("#   Run: python run.py --create-stubs\n")
        f.write("#   Review created files in 4 Library/Books/ at your pace.\n\n")
        yaml.dump(
            {"matches": results["matches"], "orphans": results["orphans_list"]},
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False
        )


if __name__ == "__main__":
    main()
