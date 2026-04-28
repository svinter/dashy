"""Ingest a URL into Libby + vault inbox.

Triggered by Keyboard Maestro with the current clipboard URL as argument.

Usage:
    cd /Users/stevevinter/dashy/app/backend
    source venv/bin/activate
    python scripts/ingest_url.py https://example.com/article
"""

import html as _html
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

# ── Path bootstrap ──────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent.parent  # app/backend
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from app_config import load_config
from database import get_write_db
from connectors.obsidian import get_vault_path, get_vault_name


# ── URL fetch + metadata extraction ─────────────────────────────────────────

def _fetch_metadata(url: str) -> dict:
    """Fetch URL and extract Open Graph / meta-tag metadata."""
    import httpx

    # YouTube oEmbed
    if "youtube.com" in url or "youtu.be" in url:
        try:
            resp = httpx.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
                timeout=8.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "title": data.get("title"),
                    "author": data.get("author_name"),
                    "description": None,
                    "published_date": None,
                }
        except Exception:
            pass

    try:
        resp = httpx.get(
            url,
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; DashyBot/1.0)"},
        )
        resp.raise_for_status()
        html_text = resp.text[:100_000]
    except Exception as exc:
        return {"title": None, "author": None, "description": None, "published_date": None,
                "error": str(exc)}

    def _og(prop: str) -> str | None:
        m = re.search(
            rf'<meta[^>]+property=["\']og:{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
            html_text, re.IGNORECASE,
        ) or re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:{re.escape(prop)}["\']',
            html_text, re.IGNORECASE,
        )
        return _html.unescape(m.group(1)).strip() if m else None

    def _meta(name: str) -> str | None:
        m = re.search(
            rf'<meta[^>]+name=["\']({re.escape(name)})["\'][^>]+content=["\']([^"\']+)["\']',
            html_text, re.IGNORECASE,
        ) or re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']({re.escape(name)})["\']',
            html_text, re.IGNORECASE,
        )
        return _html.unescape(m.group(2)).strip() if m else None

    def _title_tag() -> str | None:
        m = re.search(r"<title[^>]*>([^<]+)</title>", html_text, re.IGNORECASE)
        return _html.unescape(m.group(1)).strip() if m else None

    title = _og("title") or _meta("title") or _title_tag()
    description = _og("description") or _meta("description")
    author = _og("article:author") or _meta("author")
    published_date = _meta("article:published_time") or _og("article:published_time")
    if published_date:
        published_date = published_date[:10]  # keep YYYY-MM-DD only

    return {
        "title": title,
        "author": author,
        "description": description,
        "published_date": published_date,
    }


# ── Vault stub ───────────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "-")[:80]


def _create_vault_stub(
    vault: Path,
    vault_name: str,
    inbox_folder: str,
    title: str,
    url: str,
    author: str | None,
    published_date: str | None,
    today: str,
) -> str:
    """Write vault stub in inbox folder. Returns obsidian:// link."""
    folder_path = vault / inbox_folder
    folder_path.mkdir(parents=True, exist_ok=True)

    safe_stem = _safe_filename(title or url)
    note_path = folder_path / f"{safe_stem}.md"

    lines = ["---"]
    lines.append(f'type: ["unknown"]')
    lines.append(f'title: "{title or url}"')
    lines.append(f'url: "{url}"')
    if author:
        lines.append(f'author: "{author}"')
    if published_date:
        lines.append(f"published: {published_date}")
    lines.append(f"created: {today}")
    lines.append("needs_review: true")
    lines.append("---")
    lines.append("")
    lines.append("## Notes")
    lines.append("")

    if not note_path.exists():
        note_path.write_text("\n".join(lines), encoding="utf-8")

    rel = str(note_path.relative_to(vault))
    return f"obsidian://open?vault={quote(vault_name or '')}&file={quote(rel)}"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/ingest_url.py <url>", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1].strip()
    if not url.startswith("http"):
        print(f"Not a URL: {url}", file=sys.stderr)
        sys.exit(1)

    libby_cfg = load_config().get("libby", {})
    inbox_folder = libby_cfg.get("inbox_vault_folder", "4 Library/Inbox")

    print(f"Fetching {url} …", end=" ", flush=True)
    meta = _fetch_metadata(url)

    if meta.get("error"):
        print(f"WARN: could not fetch page ({meta['error']}) — creating stub with URL only")

    title = meta.get("title") or url
    author = meta.get("author")
    description = meta.get("description")
    published_date = meta.get("published_date")
    today = date.today().isoformat()

    print(f'"{title}"')

    vault = get_vault_path()
    vault_name = get_vault_name() or ""
    obsidian_link = None

    if vault:
        obsidian_link = _create_vault_stub(
            vault, vault_name, inbox_folder,
            title, url, author, published_date, today,
        )

    # Create library_items + library_entries rows
    with get_write_db() as dbw:
        cur = dbw.execute(
            "INSERT INTO library_items (author, published_date) VALUES (?, ?)",
            (author, published_date),
        )
        entity_id = cur.lastrowid

        comments = description[:300] if description else None
        cur2 = dbw.execute(
            """INSERT INTO library_entries
               (name, type_code, priority, url, comments, entity_id,
                needs_review, ingest_source, ingest_original, obsidian_link,
                needs_enrichment, created_at, updated_at)
               VALUES (?, 'u', 'medium', ?, ?, ?,
                       1, 'url', ?, ?,
                       0, datetime('now'), datetime('now'))""",
            (title, url, comments, entity_id, url, obsidian_link),
        )
        entry_id = cur2.lastrowid
        dbw.commit()

    print(f"Saved: {title} (entry #{entry_id})")
    if obsidian_link:
        print(f"Vault: {obsidian_link}")


if __name__ == "__main__":
    main()
