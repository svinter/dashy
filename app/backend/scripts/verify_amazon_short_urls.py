"""Pre-populate clean Amazon URLs for books that have a full amazon_url.

Strips tracking params: https://www.amazon.com/Title/dp/ASIN/ref=... → https://www.amazon.com/dp/ASIN

Run once after migration to warm the cache.

Usage:
    cd /Users/stevevinter/dashy/app/backend
    source venv/bin/activate
    python scripts/verify_amazon_short_urls.py
"""

import re
import sqlite3
from pathlib import Path

DB = Path.home() / ".personal-dashboard/dashboard.db"
ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")


conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT id, amazon_url FROM library_entries
    WHERE amazon_url IS NOT NULL AND amazon_url != ''
      AND amazon_short_url IS NULL
    ORDER BY priority DESC, frequency DESC
""").fetchall()

print(f"Processing {len(rows)} entries with amazon_url but no clean URL cached...")
updated = 0
skipped = 0

for row in rows:
    m = ASIN_RE.search(row["amazon_url"])
    if not m:
        skipped += 1
        continue
    clean_url = f"https://www.amazon.com/dp/{m.group(1)}"
    conn.execute(
        "UPDATE library_entries SET amazon_short_url = ? WHERE id = ?",
        (clean_url, row["id"]),
    )
    updated += 1

conn.commit()
conn.close()
print(f"Cached clean URLs: {updated} / {len(rows)} (no ASIN found: {skipped})")
