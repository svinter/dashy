"""
libby_pipeline/enrich.py — URL resolution and Google Books API enrichment
Version 1.0
"""

import re
import time
import sqlite3
import requests
from pathlib import Path
from urllib.parse import urlparse


# ── TinyURL Resolution ────────────────────────────────────────────────────────

AMAZON_ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")
REQUEST_TIMEOUT = 10
SLEEP_BETWEEN   = 0.1   # seconds between requests — be polite


def resolve_urls(db_path: Path):
    """
    For each book with a tinyurl/shortened url and no amazon_url,
    follow redirects to get the final URL. Store in amazon_url field.
    """
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()

    cur.execute("""
        SELECT e.id, e.url
        FROM library_entries e
        WHERE e.amazon_url IS NULL OR e.amazon_url = ''
        AND e.url IS NOT NULL AND e.url != ''
    """)
    rows = cur.fetchall()
    print(f"  Resolving {len(rows)} URLs...")

    resolved = 0
    failed   = 0

    for entry_id, url in rows:
        try:
            resp = requests.get(url, allow_redirects=True, timeout=REQUEST_TIMEOUT)
            final_url = resp.url

            # Extract ASIN if it's Amazon
            asin_match = AMAZON_ASIN_RE.search(final_url)
            amazon_url = final_url if "amazon.com" in final_url else ""

            cur.execute(
                "UPDATE library_entries SET amazon_url = ?, updated_at = datetime('now') WHERE id = ?",
                (amazon_url or final_url, entry_id)
            )
            resolved += 1
        except Exception as e:
            failed += 1
            print(f"    WARN: failed to resolve {url}: {e}")

        time.sleep(SLEEP_BETWEEN)

        if resolved % 100 == 0 and resolved > 0:
            conn.commit()
            print(f"    ...{resolved} resolved so far")

    conn.commit()
    conn.close()
    print(f"  Resolved: {resolved}, Failed: {failed}")


def asin_from_url(url: str) -> str:
    m = AMAZON_ASIN_RE.search(url)
    return m.group(1) if m else ""


# ── Google Books API ──────────────────────────────────────────────────────────

GBOOKS_API = "https://www.googleapis.com/books/v1/volumes"


def enrich_google_books(db_path: Path):
    """
    For each book with needs_enrichment=1, query Google Books API
    by title + author. Populate isbn, publisher, year, google_books_id.
    Vault-sourced metadata (if isbn already present) is not overwritten.
    """
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()

    cur.execute("""
        SELECT e.id, e.name, b.id as book_id, b.author, b.isbn,
               b.publisher, b.year, b.google_books_id
        FROM library_entries e
        JOIN library_books b ON b.id = e.entity_id
        WHERE e.type_code = 'b'
        AND e.needs_enrichment = 1
    """)
    rows = cur.fetchall()
    print(f"  Enriching {len(rows)} books via Google Books API...")

    enriched = 0
    not_found = 0

    for row in rows:
        entry_id, name, book_id, author, isbn, publisher, year, gb_id = row

        # Vault wins: if ISBN already set, skip API but still clear flag
        if isbn:
            cur.execute(
                "UPDATE library_entries SET needs_enrichment = 0 WHERE id = ?",
                (entry_id,)
            )
            continue

        data = _query_gbooks(name, author)
        if not data:
            not_found += 1
            cur.execute(
                "UPDATE library_entries SET needs_enrichment = 0 WHERE id = ?",
                (entry_id,)
            )
            continue

        # Extract fields
        vol_info = data.get("volumeInfo", {})
        isbn_list = {
            id_["type"]: id_["identifier"]
            for id_ in vol_info.get("industryIdentifiers", [])
        }
        new_isbn      = isbn_list.get("ISBN_13") or isbn_list.get("ISBN_10") or ""
        new_publisher = vol_info.get("publisher", "")
        new_year      = _extract_year(vol_info.get("publishedDate", ""))
        new_gb_id     = data.get("id", "")
        new_cover     = (vol_info.get("imageLinks") or {}).get("thumbnail", "")

        cur.execute("""
            UPDATE library_books
            SET isbn            = COALESCE(NULLIF(isbn, ''), ?),
                publisher       = COALESCE(NULLIF(publisher, ''), ?),
                year            = COALESCE(NULLIF(year, ''), ?),
                google_books_id = COALESCE(NULLIF(google_books_id, ''), ?),
                cover_url       = COALESCE(NULLIF(cover_url, ''), ?)
            WHERE id = ?
        """, (new_isbn, new_publisher, new_year, new_gb_id, new_cover, book_id))

        cur.execute(
            "UPDATE library_entries SET needs_enrichment = 0, updated_at = datetime('now') WHERE id = ?",
            (entry_id,)
        )
        enriched += 1
        time.sleep(0.05)

        if enriched % 100 == 0:
            conn.commit()
            print(f"    ...{enriched} enriched so far")

    conn.commit()
    conn.close()
    print(f"  Enriched: {enriched}, Not found: {not_found}")


def _query_gbooks(title: str, author: str) -> dict | None:
    """Query Google Books API. Returns first result volumeInfo or None."""
    # Clean title for query — drop subtitle
    short_title = title.split(":")[0].strip()
    query = f'intitle:"{short_title}"'
    if author:
        # Use first author name only
        first_author = author.split(",")[0].strip()
        query += f'+inauthor:"{first_author}"'

    try:
        resp = requests.get(
            GBOOKS_API,
            params={"q": query, "maxResults": 1, "printType": "books"},
            timeout=10
        )
        data = resp.json()
        items = data.get("items")
        if items:
            return items[0]
    except Exception as e:
        print(f"    WARN: Google Books API error for '{title}': {e}")
    return None


def _extract_year(date_str: str) -> int | None:
    m = re.match(r"(\d{4})", date_str)
    return int(m.group(1)) if m else None
