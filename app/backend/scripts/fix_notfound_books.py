"""
Fix 13 library entries with Amazon short URLs.
For each: resolve a.co short URL → full URL + ASIN,
query Google Books by ISBN (ASIN), update DB fields,
reset needs_enrichment, remove from not-found log.
"""
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATA_DIR = Path.home() / ".personal-dashboard"
DB_PATH = DATA_DIR / "dashboard.db"
CONFIG_PATH = DATA_DIR / "config.json"

with open(CONFIG_PATH) as f:
    _cfg = json.load(f)
BOOKS_API_KEY = _cfg["secrets"]["GOOGLE_BOOKS_API_KEY"]

FIXES = [
    (451,  "https://a.co/d/08GC2sUX"),   # 4 Essential Keys to Effective Communication
    (496,  "https://a.co/d/0b3zxe8p"),   # All the World
    (533,  "https://a.co/d/00ZBmCFh"),   # Becoming an Exceptional Executive Coach
    (691,  "https://a.co/d/0eAElVos"),   # Emotional Intelligence 2.0
    (760,  "https://a.co/d/0dRiVYSc"),   # Get Out of My Life
    (800,  "https://a.co/d/09LHCphL"),   # Having the Life You Want
    (921,  "https://a.co/d/03dYQmVg"),   # Listening Speaking and Dialogue Skills
    (1116, "https://a.co/d/04m8nFFr"),   # Solving America's Health Care Crisis
    (1175, "https://a.co/d/0d5vGNyp"),   # The Agility Factor
    (1217, "https://a.co/d/06FO2fOO"),   # The Change Handbook
    (1247, "https://a.co/d/0hkduF1M"),   # The Discipline of Teams
    (1332, "https://a.co/d/05ptw6nD"),   # The Kill Chain
    (1459, "https://a.co/d/0aoCUr1A"),   # Wisdom from the World's Greatest CEOs
]

ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_short_url(short_url: str, client: httpx.Client) -> tuple[str, str | None]:
    """Follow redirects to get full URL; extract ASIN from path."""
    try:
        r = client.get(short_url, follow_redirects=True, timeout=15)
        full_url = str(r.url)
        m = ASIN_RE.search(full_url)
        asin = m.group(1) if m else None
        return full_url, asin
    except Exception as e:
        print(f"  ERROR resolving {short_url}: {e}")
        return short_url, None


def query_google_books_isbn(asin: str) -> dict | None:
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{asin}&key={BOOKS_API_KEY}"
    try:
        r = httpx.get(url, timeout=15)
        data = r.json()
        items = data.get("items", [])
        if items:
            return items[0]
    except Exception as e:
        print(f"  ERROR querying Books by ISBN {asin}: {e}")
    return None


def query_google_books_title(title: str) -> dict | None:
    q = title.replace(" ", "+")
    url = f"https://www.googleapis.com/books/v1/volumes?q={q}&key={BOOKS_API_KEY}"
    try:
        r = httpx.get(url, timeout=15)
        data = r.json()
        items = data.get("items", [])
        if items:
            return items[0]
    except Exception as e:
        print(f"  ERROR querying Books by title '{title}': {e}")
    return None


def extract_info(vol: dict) -> dict:
    info = vol.get("volumeInfo", {})
    iids = info.get("industryIdentifiers", [])
    isbn13 = next((x["identifier"] for x in iids if x["type"] == "ISBN_13"), None)
    isbn10 = next((x["identifier"] for x in iids if x["type"] == "ISBN_10"), None)
    isbn = isbn13 or isbn10

    authors_list = info.get("authors", [])
    author = authors_list[0] if authors_list else None
    authors_json = json.dumps(authors_list) if authors_list else None

    cats = info.get("categories", [])
    categories_json = json.dumps(cats) if cats else None

    pub_date = info.get("publishedDate", "")
    year = pub_date[:4] if pub_date and len(pub_date) >= 4 else None

    return {
        "title": info.get("title"),
        "subtitle": info.get("subtitle"),
        "author": author,
        "authors": authors_json,
        "isbn": isbn,
        "publisher": info.get("publisher"),
        "year": int(year) if year and year.isdigit() else None,
        "categories": categories_json,
        "preview_link": (vol.get("accessInfo", {}) or {}).get("webReaderLink") or info.get("previewLink"),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # Use a browser-like UA to avoid Amazon bot blocks
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    client = httpx.Client(headers=headers, follow_redirects=True)

    results = []

    for entry_id, short_url in FIXES:
        row = db.execute(
            "SELECT e.id, e.name, e.entity_id, b.author, b.isbn "
            "FROM library_entries e "
            "JOIN library_books b ON b.id = e.entity_id "
            "WHERE e.id = ?",
            (entry_id,),
        ).fetchone()

        if not row:
            print(f"[{entry_id}] NOT FOUND in DB — skipping")
            results.append((entry_id, "missing", None, None))
            continue

        current_name = row["name"]
        entity_id = row["entity_id"]
        print(f"\n[{entry_id}] {current_name}")

        # 1. Resolve short URL
        full_url, asin = resolve_short_url(short_url, client)
        clean_dp_url = f"https://www.amazon.com/dp/{asin}" if asin else full_url
        print(f"  ASIN: {asin} — {clean_dp_url}")
        time.sleep(0.5)

        # 2. Query Google Books
        book_info = None
        source = None
        if asin:
            book_info = query_google_books_isbn(asin)
            if book_info:
                source = f"ISBN:{asin}"
            time.sleep(0.3)

        if not book_info:
            book_info = query_google_books_title(current_name)
            source = f"title:{current_name}" if book_info else None
            time.sleep(0.3)

        # 3. Update DB
        if book_info:
            info = extract_info(book_info)
            new_title = info["title"] or current_name
            print(f"  Found via {source}: '{new_title}' by {info['author']} ({info['year']})")

            db.execute(
                "UPDATE library_entries SET name = ?, amazon_url = ?, needs_enrichment = 0 WHERE id = ?",
                (new_title, clean_dp_url, entry_id),
            )
            db.execute(
                """UPDATE library_books SET
                    author = ?, isbn = ?, publisher = ?, year = ?,
                    subtitle = ?, categories = ?, authors = ?,
                    preview_link = ?
                   WHERE id = ?""",
                (
                    info["author"], info["isbn"], info["publisher"], info["year"],
                    info["subtitle"], info["categories"], info["authors"],
                    info["preview_link"],
                    entity_id,
                ),
            )
            results.append((entry_id, "updated", new_title, info["author"]))
        else:
            print(f"  NOT FOUND via Google Books — updating URL only")
            db.execute(
                "UPDATE library_entries SET amazon_url = ?, needs_enrichment = 0 WHERE id = ?",
                (clean_dp_url, entry_id),
            )
            results.append((entry_id, "url_only", current_name, None))

        # 4. Remove from not-found log
        db.execute("DELETE FROM library_enrich_not_found WHERE entry_id = ?", (entry_id,))

    db.commit()
    db.close()
    client.close()

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for entry_id, status, title, author in results:
        marker = "✓" if status == "updated" else ("~" if status == "url_only" else "✗")
        label = f"{title} / {author}" if title else "(missing)"
        print(f"  {marker} [{entry_id}] {status:10s}  {label}")


if __name__ == "__main__":
    main()
