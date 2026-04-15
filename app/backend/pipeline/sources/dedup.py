"""
libby_pipeline/dedup.py — Deduplication and merge
Version 1.0

Authority: ground_truth wins on title/author.
Merges status, priority, comments, topics from other sources.
Flags true conflicts for manual review.
"""

from parse import BookRecord, normalize_title
from typing import Optional
import difflib


def dedup_and_merge(staging: dict) -> dict:
    """
    Deduplicate books list against itself (ground_truth is the spine).
    Returns merged dict with:
      books:      [BookRecord]  — deduplicated
      unresolved: [UnresolvedRecord]
      conflicts:  [(BookRecord, BookRecord, field, val_a, val_b)]
    """
    books     = staging["books"]
    conflicts = []
    seen      = {}   # normalized_title → index in merged list
    merged    = []

    for book in books:
        norm = normalize_title(book.title)

        if norm not in seen:
            seen[norm] = len(merged)
            merged.append(book)
        else:
            # Duplicate — merge non-empty fields into existing record
            existing = merged[seen[norm]]
            _merge_record(existing, book, conflicts)

    # Deduplicate unresolved by url
    seen_urls = set()
    unresolved_deduped = []
    for r in staging["unresolved"]:
        if r.url not in seen_urls:
            seen_urls.add(r.url)
            unresolved_deduped.append(r)

    print(f"  Dedup: {len(books)} → {len(merged)} unique books")
    print(f"  Conflicts flagged for review: {len(conflicts)}")
    print(f"  Unresolved: {len(staging['unresolved'])} → {len(unresolved_deduped)} after dedup")

    return {
        "books":      merged,
        "unresolved": unresolved_deduped,
        "conflicts":  conflicts,
    }


def _merge_record(existing: BookRecord, incoming: BookRecord, conflicts: list):
    """
    Merge incoming into existing. ground_truth (existing) wins on title/author.
    Non-empty supplementary fields fill gaps.
    True conflicts (different values for same field) are logged.
    """
    # Fields where incoming can fill a gap
    fillable = ["comments", "gdoc_summary_id", "highlights_path", "summary_path"]
    for field in fillable:
        existing_val = getattr(existing, field)
        incoming_val = getattr(incoming, field)
        if not existing_val and incoming_val:
            setattr(existing, field, incoming_val)

    # Status: prefer more specific
    STATUS_RANK = {"reading": 2, "read": 1, "unread": 0}
    if STATUS_RANK.get(incoming.status, 0) > STATUS_RANK.get(existing.status, 0):
        existing.status = incoming.status

    # Priority: prefer higher
    PRIORITY_RANK = {"high": 2, "medium": 1, "low": 0}
    if PRIORITY_RANK.get(incoming.priority, 0) > PRIORITY_RANK.get(existing.priority, 0):
        existing.priority = incoming.priority

    # Topics: union
    for t in incoming.topics:
        if t not in existing.topics:
            existing.topics.append(t)

    # Tags: union
    for t in incoming.tags:
        if t not in existing.tags:
            existing.tags.append(t)

    # Flag author conflicts (different non-empty authors)
    if (existing.author and incoming.author and
            existing.author.lower() != incoming.author.lower()):
        # Only flag if names are meaningfully different (not just formatting)
        similarity = difflib.SequenceMatcher(
            None, existing.author.lower(), incoming.author.lower()
        ).ratio()
        if similarity < 0.8:
            conflicts.append((
                existing, incoming,
                "author", existing.author, incoming.author
            ))
