#!/usr/bin/env python3
"""Process Book Summaries.md to extract and match Drive/external summary links to library_books.

Source: /Users/stevevinter/Obsidian/MyNotes/9 Unfiled/Book Summaries.md

Usage:
    python scripts/process_book_summaries.py --dry-run   # show matches, no writes
    python scripts/process_book_summaries.py --apply     # write high-confidence matches to DB
"""

import argparse
import json
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

SOURCE = Path("/Users/stevevinter/Obsidian/MyNotes/9 Unfiled/Book Summaries.md")
DB_PATH = Path.home() / ".personal-dashboard/dashboard.db"

HIGH_CONFIDENCE = 85
NEEDS_REVIEW = 65

# Single doc that the "Reading Notes on Books" section bookmarks into — skip all anchors
_SKIP_DOC_IDS = {
    "1KaK7O8JgSem3L8Z8AWTZxiiVZ3i847ADnTpq3XHrys0",  # Reading Notes on Books
    "1zTj4QXH5xPELs9Wl7mrQKbldTIdamiyRxYvClGqv-XY",  # Book Summary master doc
}

# Site-level URLs to skip
_SKIP_URL_CONTAINS = [
    "designepiclife.com",
    "jamesstuber.com/booknotes",
    "alonewithbooks.com/index",
    "blinkist.com",
    "scribd.com",
    "slooowdown.wordpress.com",
    "nateliason.com/notes",
    "tosummarise.com/all-summaries",
    "notion.so",
    "youtube.com",
    "whatmatters.com/resources",
    "fourminutebooks.com/book-summaries",
    "samuelthomasdavies.com/book-summaries",
    "sivers.org/book",
]

# Regex patterns
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)')
_WIKI_RE = re.compile(r'\[\[([^\]]+)\]\]')
_DRIVE_OPEN_RE = re.compile(r'[?&]id=([A-Za-z0-9_-]+)')
_DOCS_PATH_RE = re.compile(r'/document/d/([A-Za-z0-9_-]+)')


def extract_gdoc_id(url: str) -> str | None:
    m = _DRIVE_OPEN_RE.search(url)
    if m:
        return m.group(1)
    m = _DOCS_PATH_RE.search(url)
    if m:
        return m.group(1)
    return None


def is_drive_url(url: str) -> bool:
    return "drive.google.com" in url or "docs.google.com" in url


def should_skip_url(url: str) -> bool:
    for pat in _SKIP_URL_CONTAINS:
        if pat in url:
            return True
    gdoc_id = extract_gdoc_id(url)
    if gdoc_id and gdoc_id in _SKIP_DOC_IDS:
        return True
    # Skip bookmark anchors into any single doc (same-doc references)
    if "#bookmark=" in url or "#heading=" in url:
        return True
    return False


def wiki_title(raw: str) -> str:
    """Strip path prefix from wiki titles like '4 Library/Books/Good Strategy, Bad Strategy'."""
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    return raw.strip()


def normalize(name: str) -> str:
    """Normalize for fuzzy matching."""
    name = re.sub(r"[:\-–—]", " ", name)
    name = re.sub(r"\s+", " ", name).strip().lower()
    if name.startswith("the "):
        name = name[4:]
    # Handle ALL CAPS (acronym/title) — just lowercase is fine
    return name


def score(a: str, b: str) -> int:
    return int(SequenceMatcher(None, normalize(a), normalize(b)).ratio() * 100)


def parse_entries(text: str) -> list[dict]:
    """Extract (title, url, url_type) from Book Summaries.md."""
    entries: list[dict] = []
    seen_urls: set[str] = set()

    for line in text.splitlines():
        # Extract any wiki title on this line (first one)
        wiki_match = _WIKI_RE.search(line)
        wiki = wiki_title(wiki_match.group(1)) if wiki_match else None

        # Find all markdown links on this line
        md_links = _MD_LINK_RE.findall(line)
        if not md_links:
            continue

        for link_text, url in md_links:
            url = url.strip()
            if url in seen_urls:
                continue
            if should_skip_url(url):
                continue

            # Determine title: prefer wiki title, fall back to link text
            # But only use wiki title if it's not a generic word like "link", "summary", etc.
            generic_texts = {"link", "summary", "here", "below", "site", "notes"}
            if wiki and link_text.strip().lower() in generic_texts:
                title = wiki
            elif wiki and len(link_text) < len(wiki) // 2:
                # Link text is too short relative to wiki title — use wiki
                title = wiki
            else:
                title = wiki if wiki else link_text.strip()

            # Skip if title looks like a site listing, not a book
            if any(skip in title.lower() for skip in ["40 top", "see list", "great site", "reading notes"]):
                continue

            seen_urls.add(url)
            drive = is_drive_url(url)
            gdoc_id = extract_gdoc_id(url) if drive else None
            entries.append({
                "title": title,
                "url": url,
                "is_drive": drive,
                "gdoc_id": gdoc_id,
            })

    return entries


def load_books(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT e.id AS entry_id, e.name, e.entity_id AS book_id, "
        "b.gdoc_summary_id, b.external_summary_url "
        "FROM library_entries e "
        "JOIN library_books b ON b.id = e.entity_id "
        "WHERE e.type_code = 'b'"
    ).fetchall()


def match_entries(entries: list[dict], books: list[sqlite3.Row]) -> tuple[list, list, list]:
    high, review, none_ = [], [], []
    for entry in entries:
        best_score = 0
        best_book = None
        for book in books:
            s = score(entry["title"], book["name"])
            if s > best_score:
                best_score = s
                best_book = book
        item = {**entry, "book": best_book, "match_score": best_score}
        if best_score >= HIGH_CONFIDENCE:
            high.append(item)
        elif best_score >= NEEDS_REVIEW:
            review.append(item)
        else:
            none_.append(item)
    return high, review, none_


def fmt_url_type(item: dict) -> str:
    if item["is_drive"] and item["gdoc_id"]:
        return f"Drive: gdoc_id={item['gdoc_id']}"
    return f"External: {item['url']}"


def main():
    parser = argparse.ArgumentParser(description="Match Book Summaries.md links to library_books.")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args()
    if not args.apply:
        args.dry_run = True

    text = SOURCE.read_text(encoding="utf-8")
    entries = parse_entries(text)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    books = load_books(conn)

    if not books:
        print("No book records found.")
        conn.close()
        return

    high, review, none_ = match_entries(entries, books)

    drive_count = sum(1 for e in entries if e["is_drive"])
    external_count = sum(1 for e in entries if not e["is_drive"])

    label = "Book Summaries Dry Run" if args.dry_run else "Book Summaries — APPLYING"
    print(label)
    print("=" * 40)

    print(f"\nHIGH CONFIDENCE (≥{HIGH_CONFIDENCE}): {len(high)}")
    for item in high:
        book = item["book"]
        print(f'  "{item["title"]}" → "{book["name"]}" (id={book["entry_id"]}, score={item["match_score"]})')
        print(f'    {fmt_url_type(item)}')

    print(f"\nNEEDS REVIEW ({NEEDS_REVIEW}–{HIGH_CONFIDENCE - 1}): {len(review)}")
    for item in review:
        book = item["book"]
        print(f'  "{item["title"]}" → "{book["name"]}" (score={item["match_score"]})')
        print(f'    {fmt_url_type(item)}')

    print(f"\nNO MATCH / FLAG FOR REVIEW: {len(none_)}")
    for item in none_:
        book = item["book"]
        reason = f'best: "{book["name"]}" (score={item["match_score"]})' if book else "no books in DB"
        print(f'  "{item["title"]}" — {reason}')
        print(f'    {fmt_url_type(item)}')

    print(f"\nTOTALS: {len(high)} high / {len(review)} review / {len(none_)} no-match")
    print(f"  Drive summaries: {drive_count}")
    print(f"  External URLs  : {external_count}")

    if not args.dry_run and args.apply:
        updated = 0
        for item in high:
            book = item["book"]
            if item["is_drive"] and item["gdoc_id"]:
                if not book["gdoc_summary_id"]:
                    conn.execute(
                        "UPDATE library_books SET gdoc_summary_id = ? WHERE id = ?",
                        (item["gdoc_id"], book["book_id"]),
                    )
                    updated += 1
            else:
                # Store as JSON array (accumulate multiple per book)
                existing = book["external_summary_url"]
                urls = json.loads(existing) if existing else []
                if item["url"] not in urls:
                    urls.append(item["url"])
                    conn.execute(
                        "UPDATE library_books SET external_summary_url = ? WHERE id = ?",
                        (json.dumps(urls), book["book_id"]),
                    )
                    updated += 1
        conn.commit()
        print(f"\nUpdated {updated} rows.")

    conn.close()


if __name__ == "__main__":
    main()
