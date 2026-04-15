"""
libby_pipeline/report.py — Dry run report formatting
Version 1.0
"""

from datetime import date


def dry_run_report(staging: dict, merged: dict):
    """Print full dry run report to stdout."""
    books_gt   = staging["books"]
    unresolved = staging["unresolved"]

    # Source counts
    gbooks_status   = staging.get("gbooks_status", {})
    gbooks_favs     = staging.get("gbooks_favorites", set())
    favorites       = staging.get("favorites_titles", set())
    summaries       = staging.get("summaries", {})
    curated_annots  = staging.get("curated_annotations", {})

    have_read    = sum(1 for s in gbooks_status.values() if s == "read")
    to_read      = sum(1 for s in gbooks_status.values() if s == "unread")
    reading_now  = sum(1 for s in gbooks_status.values() if s == "reading")
    gbooks_total = len(gbooks_status)

    merged_books   = merged["books"]
    conflicts      = merged.get("conflicts", [])
    unresolved_d   = merged["unresolved"]

    n_high         = sum(1 for b in merged_books if b.priority == "high")
    n_read         = sum(1 for b in merged_books if b.status == "read")
    n_with_topics  = sum(1 for b in merged_books if b.topics or b.tags)
    n_with_annot   = sum(1 for b in merged_books if b.comments)
    n_with_summary = sum(1 for b in merged_books if b.gdoc_summary_id)

    tinyurl_count  = sum(
        1 for b in merged_books
        if b.url and "tinyurl.com" in b.url
    )

    print(f"\nLibby Pipeline Dry Run — {date.today()}")
    print("=" * 53)

    print("\nSOURCE PARSING")
    print(f"  ground_truth.txt")
    print(f"    → books                     {len(books_gt):>6}")
    print(f"    → unresolved (non-book)      {len(unresolved):>6}")
    print(f"  Curated.md")
    print(f"    → annotations found          {len(curated_annots):>6}")
    print(f"  Favorites.md")
    print(f"    → titles (all read/high)     {len(favorites):>6}")
    print(f"  Summaries.md")
    print(f"    → Drive-linked summaries     {len(summaries):>6}")
    print(f"  Google Books PDF")
    print(f"    → total entries              {gbooks_total:>6}")
    print(f"      Have read                  {have_read:>6}")
    print(f"      To read                    {to_read:>6}")
    print(f"      Reading now                {reading_now:>6}")
    print(f"      Favorites                  {len(gbooks_favs):>6}")

    print("\nDEDUPLICATION")
    print(f"  Unique books after merge       {len(merged_books):>6}")
    print(f"  Duplicates collapsed           {len(books_gt) - len(merged_books):>6}")
    print(f"  Conflicts flagged for review   {len(conflicts):>6}")
    print(f"  Unresolved entries             {len(unresolved_d):>6}")

    print("\nENRICHMENT (estimated)")
    print(f"  Books with priority=high       {n_high:>6}")
    print(f"  Books with status=read         {n_read:>6}")
    print(f"  Books with topic assignments   {n_with_topics:>6}")
    print(f"  Books with annotations         {n_with_annot:>6}")
    print(f"  Books with summary Drive link  {n_with_summary:>6}")

    print("\nTINYURL RESOLUTION (estimated)")
    print(f"  URLs to resolve                {tinyurl_count:>6}")
    print(f"  Estimated success rate            ~96%")
    print(f"  Estimated run time              ~{max(1, tinyurl_count // 60)} min")

    print("\nVAULT RECONCILIATION")
    print(f"  (Run --vault-scan after --load to get vault counts)")

    print("\nNOTE: No files or database were modified.")
    print("Run without --dry-run to execute each phase.")
