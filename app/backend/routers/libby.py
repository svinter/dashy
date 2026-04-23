"""Libby — personal library management module.

Design: ~/Obsidian/MyNotes/Projects/Dashy/libby-design.md

Endpoints:
  GET  /api/libby/search                       — keyword + type + topic search
  GET  /api/libby/active-client                — default client for current session
  GET  /api/libby/queue                        — entries awaiting enrichment
  POST /api/libby/entries                      — create a new library entry
  POST /api/libby/entries/{id}/action/copy     — return URL for clipboard
  POST /api/libby/entries/{id}/action/record   — log share, write Obsidian notes, append to Manifest
  POST /api/libby/entries/{id}/action/make     — generate GitHub Pages HTML, git push, set webpage_url
"""

import html as _html
import logging
import re
import subprocess
from datetime import date as _date, datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from database import get_db, get_write_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/libby", tags=["libby"])

# ---------------------------------------------------------------------------
# Type-counts cache
# ---------------------------------------------------------------------------

_type_counts_cache: dict[str, int] | None = None


def _invalidate_type_counts_cache() -> None:
    global _type_counts_cache
    _type_counts_cache = None


def _get_type_counts(db) -> dict[str, int]:
    global _type_counts_cache
    if _type_counts_cache is not None:
        return _type_counts_cache
    rows = db.execute(
        "SELECT type_code, COUNT(*) AS cnt FROM library_entries GROUP BY type_code"
    ).fetchall()
    _type_counts_cache = {row[0]: row[1] for row in rows}
    return _type_counts_cache


@router.get("/type-counts")
def get_type_counts():
    """Return entry count per type code. Cached in-process; invalidated on entry creation."""
    db = get_db()
    return _get_type_counts(db)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}
_VALID_TYPE_CODES = frozenset({"a", "b", "e", "p", "v", "m", "t", "w", "s", "z", "n", "d", "f", "c", "r", "q"})
_TYPE_NAMES = {
    "b": "Book",        "a": "Article",    "e": "Essay",
    "p": "Podcast",     "v": "Video",      "m": "Movie",
    "t": "Tool",        "w": "Webpage",    "s": "Worksheet",
    "z": "Assessment",  "n": "Note",       "d": "Document",
    "f": "Framework",   "c": "Course",     "r": "Research",
    "q": "Quote",
}


# ---------------------------------------------------------------------------
# Query parsing helpers
# ---------------------------------------------------------------------------

def _parse_query(q: str) -> tuple[str | None, list[str], list[str]]:
    """Parse Libby search syntax into (type_code, topic_prefixes, name_tokens).

    Grammar:
      single letter matching a known type code  → type filter
      .xx                                        → topic prefix match
      everything else                            → name AND match
    """
    type_code: str | None = None
    topic_prefixes: list[str] = []
    name_tokens: list[str] = []

    # Normalize dots that are attached to a preceding word (e.g. "book.le" → "book .le")
    q = re.sub(r'(?<=\S)\.', ' .', q)

    tokens = q.strip().split()

    for i, token in enumerate(tokens):
        if token.startswith(".") and len(token) > 1:
            topic_prefixes.append(token[1:].lower())
        elif i == 0 and len(token) == 1 and token.lower() in _VALID_TYPE_CODES:
            # Only the first token can be a type code.
            # Exception: "a" doubles as the English indefinite article and is
            # extremely common in titles ("A Civil Action", "A Team", …).
            # Treat it as a type code only when no name tokens follow — i.e.
            # the query is just "a" or "a .topic".
            remaining_name = [t for t in tokens[i + 1:] if not (t.startswith(".") and len(t) > 1)]
            if token.lower() == 'a' and remaining_name:
                name_tokens.append(token.lower())
            else:
                type_code = token.lower()
        else:
            name_tokens.append(token.lower())

    return type_code, topic_prefixes, name_tokens


def _name_match_score(name: str, name_tokens: list[str]) -> int:
    """Score name match quality.

    Start-of-word match → 2 pts per token; mid-word → 1 pt.
    Returns 0 if any token is missing (AND semantics).
    """
    name_lower = name.lower()
    score = 0
    for tok in name_tokens:
        if tok not in name_lower:
            return 0
        if re.search(r"(?:^|\s)" + re.escape(tok), name_lower):
            score += 2
        else:
            score += 1
    return score


# ---------------------------------------------------------------------------
# GET /api/libby/search
# ---------------------------------------------------------------------------

@router.get("/search")
def search_library(q: str = "", client_id: int | None = None):
    """Search library entries using Libby query syntax.

    Returns up to 26 results ranked by: priority → name-match quality → frequency.
    When client_id is provided, each result includes last_shared_at (most recent
    share date for that entry + client), or null if never shared.
    Books also match on author; title matches rank higher than author-only matches.
    """
    import json as _json
    type_code, topic_prefixes, name_tokens = _parse_query(q)
    db = get_db()

    sql = """
        SELECT
            e.id,
            e.name,
            e.type_code,
            e.priority,
            e.frequency,
            e.url,
            e.amazon_url,
            e.amazon_short_url,
            e.webpage_url,
            e.gdoc_id,
            e.comments,
            e.obsidian_link,
            lb.categories,
            COALESCE(lb.author, li.author) AS author,
            lb.year,
            lb.isbn,
            lb.subtitle,
            lb.preview_link,
            li.publication,
            li.published_date,
            li.show_name,
            li.episode,
            li.host,
            li.text        AS quote_text,
            li.attribution,
            li.context,
            li.notes       AS synopsis,
            e.private
        FROM library_entries e
        LEFT JOIN library_books lb ON e.type_code = 'b' AND e.entity_id = lb.id
        LEFT JOIN library_items li ON e.type_code != 'b' AND e.entity_id = li.id
        WHERE 1=1
    """
    params: list = []

    if type_code:
        sql += " AND e.type_code = ?"
        params.append(type_code)

    for tok in name_tokens:
        sql += """
            AND (
                lower(e.name) LIKE ?
                OR (e.type_code = 'q' AND lower(e.comments) LIKE ?)
                OR (e.type_code = 'b' AND lower(lb.author) LIKE ?)
            )
        """
        params.extend([f"%{tok}%", f"%{tok}%", f"%{tok}%"])

    for pfx in topic_prefixes:
        sql += """
            AND e.id IN (
                SELECT jet.entry_id
                FROM library_entry_topics jet
                JOIN library_topics jt ON jet.topic_id = jt.id
                WHERE lower(jt.name) LIKE ?
            )
        """
        params.append(f"{pfx}%")

    rows = db.execute(sql, params).fetchall()

    # Bulk-fetch topics for matched entries
    topics_by_entry: dict[int, list[dict]] = {}
    if rows:
        entry_ids = [r["id"] for r in rows]
        ph = ",".join("?" * len(entry_ids))
        for tr in db.execute(
            f"""
            SELECT jet.entry_id, lt.id AS topic_id, lt.code, lt.name
            FROM library_entry_topics jet
            JOIN library_topics lt ON jet.topic_id = lt.id
            WHERE jet.entry_id IN ({ph})
            """,
            entry_ids,
        ).fetchall():
            topics_by_entry.setdefault(tr["entry_id"], []).append(
                {"id": tr["topic_id"], "code": tr["code"], "name": tr["name"]}
            )

    def _quote_author(comments: str | None) -> str | None:
        if not comments:
            return None
        idx = comments.find(" \u2014 ")  # em dash with spaces
        if idx < 0:
            return None
        return comments[idx + 3:].strip() or None

    # Score, rank, cap
    results = []
    for row in rows:
        name_score = _name_match_score(row["name"], name_tokens) if name_tokens else 1
        author_match = False
        if name_tokens and name_score == 0:
            # For quotes, also accept a match in comments
            if row["type_code"] == "q":
                name_score = _name_match_score(row["comments"] or "", name_tokens)
            # For books, accept a match in author (lower score than title)
            if name_score == 0 and row["type_code"] == "b" and row["author"]:
                author_score = _name_match_score(row["author"], name_tokens)
                if author_score > 0:
                    name_score = 1  # author match ranks below title match
                    author_match = True
            if name_score == 0:
                continue

        author = row["author"] or (
            _quote_author(row["comments"]) if row["type_code"] == "q" else None
        )
        categories: list[str] = []
        if row["categories"]:
            try:
                categories = _json.loads(row["categories"])
            except Exception:
                pass
        results.append({
            "id": row["id"],
            "name": row["name"],
            "type_code": row["type_code"],
            "priority": row["priority"],
            "frequency": row["frequency"],
            "url": row["url"],
            "amazon_url": row["amazon_url"],
            "amazon_short_url": row["amazon_short_url"],
            "webpage_url": row["webpage_url"],
            "gdoc_id": row["gdoc_id"],
            "obsidian_link": row["obsidian_link"],
            "author": author,
            "author_match": author_match,
            "description": row["comments"] or None,
            "categories": categories,
            "topics": topics_by_entry.get(row["id"], []),
            "year": row["year"],
            "isbn": row["isbn"],
            "subtitle": row["subtitle"],
            "preview_link": row["preview_link"],
            "publication": row["publication"],
            "published_date": row["published_date"],
            "show_name": row["show_name"],
            "episode": row["episode"],
            "host": row["host"],
            "quote_text": row["quote_text"],
            "attribution": row["attribution"],
            "context": row["context"],
            "synopsis": row["synopsis"],
            "private": bool(row["private"]),
            "_rank": (
                _PRIORITY_RANK.get(row["priority"], 0),
                name_score,
                row["frequency"],
            ),
        })

    results.sort(key=lambda r: r["_rank"], reverse=True)
    total = len(results)
    results = results[:26]
    for r in results:
        del r["_rank"]

    # Bulk-fetch last_shared_at for active client
    if client_id and results:
        entry_ids = [r["id"] for r in results]
        ph = ",".join("?" * len(entry_ids))
        share_rows = db.execute(
            f"""SELECT entry_id, MAX(shared_at) AS last_shared_at
                FROM library_share_log
                WHERE client_id = ? AND entry_id IN ({ph})
                GROUP BY entry_id""",
            [client_id] + entry_ids,
        ).fetchall()
        shared_map = {sr["entry_id"]: sr["last_shared_at"] for sr in share_rows}
        for r in results:
            r["last_shared_at"] = shared_map.get(r["id"])
    else:
        for r in results:
            r["last_shared_at"] = None

    return {"results": results, "total": total}


# ---------------------------------------------------------------------------
# GET /api/libby/active-client
# ---------------------------------------------------------------------------

@router.get("/active-client")
def get_active_client():
    """Return the most relevant billing client for the current session.

    Resolution order:
    1. First confirmed billing session today (linked via calendar_events)
    2. First upcoming coaching calendar event today (color_id 3 or 5)
    3. Next upcoming coaching calendar event (soonest future date)
    4. null if nothing found
    """
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")

    # 1 — confirmed session today
    row = db.execute(
        """
        SELECT bc.id, bc.name, bc.obsidian_name
        FROM billing_sessions bs
        JOIN billing_clients bc ON bs.client_id = bc.id
        JOIN calendar_events ce ON bs.calendar_event_id = ce.id
        WHERE bs.is_confirmed = 1
          AND date(ce.start_time) = ?
          AND bs.client_id IS NOT NULL
        ORDER BY ce.start_time ASC
        LIMIT 1
        """,
        (today,),
    ).fetchone()
    if row:
        return {"id": row["id"], "name": row["name"], "obsidian_name": row["obsidian_name"]}

    # 2 — upcoming coaching event today (linked session)
    row = db.execute(
        """
        SELECT bc.id, bc.name, bc.obsidian_name
        FROM calendar_events ce
        JOIN billing_sessions bs ON bs.calendar_event_id = ce.id
        JOIN billing_clients bc ON bs.client_id = bc.id
        WHERE ce.color_id IN ('3', '5')
          AND date(ce.start_time) = ?
          AND bs.client_id IS NOT NULL
        ORDER BY ce.start_time ASC
        LIMIT 1
        """,
        (today,),
    ).fetchone()
    if row:
        return {"id": row["id"], "name": row["name"], "obsidian_name": row["obsidian_name"]}

    # 3 — next upcoming (any future date)
    row = db.execute(
        """
        SELECT bc.id, bc.name, bc.obsidian_name
        FROM calendar_events ce
        JOIN billing_sessions bs ON bs.calendar_event_id = ce.id
        JOIN billing_clients bc ON bs.client_id = bc.id
        WHERE ce.color_id IN ('3', '5')
          AND date(ce.start_time) >= ?
          AND bs.client_id IS NOT NULL
        ORDER BY ce.start_time ASC
        LIMIT 1
        """,
        (today,),
    ).fetchone()
    if row:
        return {"id": row["id"], "name": row["name"], "obsidian_name": row["obsidian_name"]}

    return None


# ---------------------------------------------------------------------------
# Obsidian write helpers (used by record action)
# ---------------------------------------------------------------------------

def _append_resource_to_meeting_note(path: Path, ref_line: str) -> bool:
    """Append ref_line to the **Resources Shared** block in a meeting note.

    Creates the block at end-of-file if not found. Returns True if modified.
    """
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")

    # Look for the bold Resources Shared header (Libby convention)
    header_re = re.compile(
        r"(\*\*Resources Shared\*\*\s*\n)((?:\s*-[^\n]*\n)*)",
        re.MULTILINE,
    )
    m = header_re.search(content)
    if m:
        # Insert new bullet immediately after the existing block
        insert_pos = m.end()
        new_content = content[:insert_pos] + ref_line + "\n" + content[insert_pos:]
    else:
        new_content = content.rstrip() + f"\n\n**Resources Shared**\n{ref_line}\n"

    path.write_text(new_content, encoding="utf-8")
    return True


def _append_resource_to_client_page(path: Path, ref_line: str) -> bool:
    """Append ref_line under ## Resources on a client's Obsidian page.

    Creates the section at end-of-file if not present. Returns True if modified.
    """
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")

    header_re = re.compile(r"^## Resources\s*$", re.IGNORECASE | re.MULTILINE)
    m = header_re.search(content)
    if m:
        body_start = m.end()
        # Find next ## heading
        next_h = re.search(r"^## ", content[body_start:], re.MULTILINE)
        if next_h:
            section_end = body_start + next_h.start()
            new_content = (
                content[:section_end].rstrip()
                + f"\n{ref_line}\n\n"
                + content[section_end:]
            )
        else:
            new_content = content.rstrip() + f"\n{ref_line}\n"
    else:
        new_content = content.rstrip() + f"\n\n## Resources\n{ref_line}\n"

    path.write_text(new_content, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Amazon clean URL helper
# ---------------------------------------------------------------------------

_AMAZON_ASIN_RE = re.compile(r'/dp/([A-Z0-9]{10})')


def _get_amazon_short_url(amazon_url: str) -> str | None:
    """Extract ASIN from amazon_url and return a clean, tracking-free URL.

    Converts e.g. https://www.amazon.com/Some-Title/dp/B000ABCDEF/ref=sr_1_1?crid=...
    to           https://www.amazon.com/dp/B000ABCDEF

    Returns None if no ASIN found.
    """
    if not amazon_url:
        return None
    match = _AMAZON_ASIN_RE.search(amazon_url)
    if not match:
        return None
    return f"https://www.amazon.com/dp/{match.group(1)}"


# ---------------------------------------------------------------------------
# POST /api/libby/entries/{id}/action/copy
# ---------------------------------------------------------------------------

@router.post("/entries/{entry_id}/action/copy")
def action_copy(entry_id: int):
    """Return the canonical URL for an entry (for clipboard copy).

    Priority chain: webpage_url → amazon_short_url (cached) → derive+cache → amazon_url → url.
    The frontend handles the actual clipboard write.
    """
    db = get_db()
    row = db.execute(
        "SELECT url, webpage_url, amazon_url, amazon_short_url FROM library_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Entry not found")

    # 1. webpage_url wins first
    if row["webpage_url"]:
        return {"url": row["webpage_url"]}

    # 2. Cached clean URL (already derived + stored)
    if row["amazon_short_url"]:
        return {"url": row["amazon_short_url"]}

    # 3. Derive + cache clean URL from full amazon_url
    if row["amazon_url"]:
        clean_url = _get_amazon_short_url(row["amazon_url"])
        if clean_url:
            db_w = get_write_db()
            db_w.execute(
                "UPDATE library_entries SET amazon_short_url = ? WHERE id = ?",
                (clean_url, entry_id),
            )
            db_w.commit()
            return {"url": clean_url}
        # No ASIN in URL — fall through to full amazon_url
        return {"url": row["amazon_url"]}

    return {"url": row["url"] or None}


# ---------------------------------------------------------------------------
# POST /api/libby/entries/{id}/action/print
# ---------------------------------------------------------------------------

@router.post("/entries/{entry_id}/action/print")
def action_print(entry_id: int):
    """Return a Markdown-formatted title + link string for clipboard.

    Books:  [{title}]({amazon_short_url|amazon_url|url}) by {author}
    Others: [{title}]({webpage_url|url})
    """
    db = get_db()
    row = db.execute(
        """SELECT e.name, e.type_code, e.url, e.amazon_url, e.amazon_short_url,
                  e.webpage_url, lb.author
           FROM library_entries e
           LEFT JOIN library_books lb ON e.type_code = 'b' AND e.entity_id = lb.id
           WHERE e.id = ?""",
        (entry_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Entry not found")

    title = row["name"]

    if row["type_code"] == "b":
        link_url = row["amazon_short_url"] or row["amazon_url"] or row["url"] or ""
        author = row["author"]
        if author:
            text = f"[{title}]({link_url}) by {author}"
        else:
            text = f"[{title}]({link_url})"
    else:
        link_url = row["webpage_url"] or row["url"] or ""
        text = f"[{title}]({link_url})"

    return {"text": text, "format": "markdown"}


# ---------------------------------------------------------------------------
# POST /api/libby/entries/{id}/action/copy_doc
# ---------------------------------------------------------------------------

def _folder_id_from_drive_url(url: str) -> str | None:
    """Extract Google Drive folder ID from a folders URL."""
    if not url:
        return None
    try:
        part = url.split("/folders/")[-1]
        return part.split("?")[0].strip() or None
    except Exception:
        return None


class CopyDocRequest(BaseModel):
    client_id: int


@router.post("/entries/{entry_id}/action/copy_doc")
def action_copy_doc(entry_id: int, body: CopyDocRequest):
    """Copy the entry's Google Doc to the client's coaching docs folder.

    Strips the "Copy of " prefix Drive adds, returns the copy URL and a
    Markdown-formatted reference line for clipboard.
    """
    db = get_db()

    entry_row = db.execute(
        "SELECT id, name, gdoc_id FROM library_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if not entry_row:
        raise HTTPException(status_code=404, detail="Entry not found")
    if not entry_row["gdoc_id"]:
        raise HTTPException(status_code=422, detail="Entry has no Google Doc")

    client_row = db.execute(
        "SELECT id, name, gdrive_coaching_docs_url FROM billing_clients WHERE id = ?",
        (body.client_id,),
    ).fetchone()
    if not client_row:
        raise HTTPException(status_code=404, detail="Client not found")
    if not client_row["gdrive_coaching_docs_url"]:
        raise HTTPException(status_code=422, detail="Client has no coaching docs folder configured")

    folder_id = _folder_id_from_drive_url(client_row["gdrive_coaching_docs_url"])
    if not folder_id:
        raise HTTPException(status_code=422, detail="Could not parse coaching docs folder URL")

    try:
        from connectors.drive import copy_drive_file
        result = copy_drive_file(
            file_id=entry_row["gdoc_id"],
            dest_folder_id=folder_id,
            original_name=entry_row["name"],
        )
    except Exception as exc:
        logger.error("copy_doc failed for entry %d: %s", entry_id, exc)
        raise HTTPException(status_code=502, detail=f"Drive API error: {exc}")

    copy_url = result["web_url"]
    filename = result["name"]
    print_text = f"[{filename}]({copy_url})"

    logger.info(
        "copy_doc: entry %d (%s) → client %d (%s), file: %s",
        entry_id, entry_row["name"], body.client_id, client_row["name"], filename,
    )
    return {"copy_url": copy_url, "print_text": print_text, "filename": filename}


# ---------------------------------------------------------------------------
# GET /api/libby/manifest/{client_id}
# ---------------------------------------------------------------------------

@router.get("/manifest/{client_id}")
def get_manifest(client_id: int):
    """Return parsed manifest contents for a client.

    Reads the client's manifest_gdoc_url, fetches the Google Doc via API,
    and parses the Documents and Others sections into structured data.

    Returns:
      {
        manifest_url: str,
        documents: [{name, url}],
        others: [{name, url, date}],
      }
    """
    db = get_db()
    row = db.execute(
        "SELECT manifest_gdoc_url FROM billing_clients WHERE id = ?", (client_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Client not found")

    manifest_url = row["manifest_gdoc_url"]
    if not manifest_url:
        raise HTTPException(status_code=404, detail="Client has no manifest")

    doc_id = _doc_id_from_url(manifest_url)
    if not doc_id:
        raise HTTPException(status_code=422, detail="Invalid manifest URL")

    try:
        from connectors.google_auth import get_google_credentials
        from googleapiclient.discovery import build

        creds = get_google_credentials()
        docs_svc = build("docs", "v1", credentials=creds)
        doc = docs_svc.documents().get(documentId=doc_id).execute()
    except Exception as exc:
        logger.error("Failed to fetch manifest doc %s: %s", doc_id, exc)
        raise HTTPException(status_code=502, detail=f"Google Docs error: {exc}")

    content = doc.get("body", {}).get("content", [])

    def _elem_link(elem: dict) -> str | None:
        """Return the first hyperlink URL found in a paragraph's textRuns."""
        for pe in elem.get("paragraph", {}).get("elements", []):
            url = pe.get("textRun", {}).get("textStyle", {}).get("link", {}).get("url")
            if url:
                return url
        return None

    documents: list[dict] = []
    others: list[dict] = []
    current_section: str | None = None  # "documents" | "others"

    for elem in content:
        if "paragraph" not in elem:
            continue

        text = _para_text(elem).strip()
        style = _para_named_style(elem)

        if style.startswith("HEADING_"):
            tl = text.lower()
            if tl.startswith("documents"):
                current_section = "documents"
            elif tl.startswith("others"):
                current_section = "others"
            else:
                current_section = None
            continue

        if not text or not text.startswith("\u2022"):
            continue

        # Strip bullet prefix "• "
        name = text.lstrip("\u2022").strip()
        url = _elem_link(elem)

        if current_section == "documents":
            documents.append({"name": name, "url": url})
        elif current_section == "others":
            # Try to extract trailing date (last token matching YYYY-MM-DD)
            import re as _re
            date_match = _re.search(r"(\d{4}-\d{2}-\d{2})\s*$", name)
            entry_date = date_match.group(1) if date_match else None
            # Strip the trailing " — date" suffix from display name
            if date_match:
                name = name[: date_match.start()].rstrip(" \u2014-").strip()
            others.append({"name": name, "url": url, "date": entry_date})

    return {
        "manifest_url": manifest_url,
        "documents": documents,
        "others": others,
    }


# ---------------------------------------------------------------------------
# Manifest Google Doc helpers (used by record action)
# ---------------------------------------------------------------------------

def _doc_id_from_url(url: str) -> str | None:
    """Extract Google Doc ID from a docs.google.com/document/d/{id}/... URL."""
    if not url:
        return None
    try:
        return url.split("/d/")[-1].split("/")[0].split("?")[0].strip() or None
    except Exception:
        return None


def _para_text(elem: dict) -> str:
    """Concatenate all textRun content strings from a paragraph structural element."""
    parts = []
    for pe in elem.get("paragraph", {}).get("elements", []):
        parts.append(pe.get("textRun", {}).get("content", ""))
    return "".join(parts)


def _para_named_style(elem: dict) -> str:
    """Return namedStyleType for a paragraph element, or empty string."""
    return (
        elem.get("paragraph", {})
        .get("paragraphStyle", {})
        .get("namedStyleType", "")
    )


def _append_to_manifest_others(doc_id: str, bullet_text: str) -> None:
    """Append a bullet line under the 'Others' heading in a Manifest Google Doc.

    Strategy:
      1. Fetch doc structure via documents().get()
      2. Scan body.content for a paragraph whose text starts with 'Others'
         (case-insensitive, stripped)
      3. Walk forward collecting non-heading paragraphs; track last non-empty one
      4. Insert "• {bullet_text}\\n" at endIndex of that last paragraph
         (or at endIndex of the heading itself if no body paragraphs exist yet)
      5. If Others heading not found, fall back to end-of-document

    Uses batchUpdate / insertText — same pattern as drive_api.py.
    Raises on any API error; caller is responsible for isolation.
    """
    from connectors.google_auth import get_google_credentials
    from googleapiclient.discovery import build

    creds = get_google_credentials()
    docs_svc = build("docs", "v1", credentials=creds)

    doc = docs_svc.documents().get(documentId=doc_id).execute()
    content = doc["body"]["content"]

    insert_index: int | None = None
    in_others = False

    for elem in content:
        if "paragraph" not in elem:
            continue

        text = _para_text(elem).strip()
        style = _para_named_style(elem)

        if not in_others:
            if text.lower().startswith("others"):
                in_others = True
                insert_index = elem["endIndex"]  # fallback: right after heading
        else:
            # Stop at any subsequent heading
            if style.startswith("HEADING_"):
                break
            # Track insert position at each non-empty paragraph
            if text:
                insert_index = elem["endIndex"]

    if insert_index is None:
        # Others heading not found — fall back to end of document
        logger.warning("Manifest doc %s: 'Others' heading not found, appending at end", doc_id)
        insert_index = content[-1]["endIndex"] - 1

    line = f"\u2022 {bullet_text}\n"  # • bullet + text + newline

    docs_svc.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{"insertText": {"location": {"index": insert_index}, "text": line}}]},
    ).execute()


# ---------------------------------------------------------------------------
# POST /api/libby/entries/{id}/action/record
# ---------------------------------------------------------------------------

class RecordRequest(BaseModel):
    client_id: int
    meeting_date: str | None = None  # defaults to today (localtime)


@router.post("/entries/{entry_id}/action/record")
def action_record(entry_id: int, body: RecordRequest):
    """Record that a resource was shared with a client.

    Writes:
    1. library_entries.frequency += 1
    2. **Resources Shared** bullet in today's Obsidian meeting note
    3. ## Resources bullet on the client's Obsidian page
    4. library_share_log row
    5. Append bullet to Others section of client's Manifest Google Doc
       (skipped silently if manifest_gdoc_url is null; failure is non-fatal)
    """
    from connectors.obsidian import get_vault_path

    db_r = get_db()

    # --- Validate entry (include amazon_url for Manifest link fallback) ---
    entry_row = db_r.execute(
        "SELECT id, name, type_code, url, webpage_url, amazon_url FROM library_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if not entry_row:
        raise HTTPException(status_code=404, detail="Entry not found")

    # --- Validate client (include manifest_gdoc_url) ---
    client_row = db_r.execute(
        "SELECT id, name, obsidian_name, manifest_gdoc_url FROM billing_clients WHERE id = ?",
        (body.client_id,),
    ).fetchone()
    if not client_row:
        raise HTTPException(status_code=404, detail="Client not found")

    vault = get_vault_path()
    if not vault:
        raise HTTPException(status_code=500, detail="Obsidian vault not configured")

    meeting_date = body.meeting_date or _date.today().isoformat()
    client_obs_name = client_row["obsidian_name"] or client_row["name"]
    type_label = _TYPE_NAMES.get(entry_row["type_code"], entry_row["type_code"])

    # Build the reference line (design doc §9 format)
    resource_url = entry_row["webpage_url"] or entry_row["url"] or ""
    if resource_url:
        ref_line = f"- [[{entry_row['name']}]] ({type_label}) — {resource_url}"
    else:
        ref_line = f"- [[{entry_row['name']}]] ({type_label})"

    messages: list[str] = []

    # 1 — meeting note
    meeting_path = vault / "8 Meetings" / f"{meeting_date} - {client_obs_name}.md"
    if _append_resource_to_meeting_note(meeting_path, ref_line):
        messages.append(f"added to {meeting_path.name}")
    else:
        messages.append(f"meeting note not found ({meeting_path.name})")

    # 2 — client page
    client_page = vault / "1 People" / f"{client_obs_name}.md"
    if _append_resource_to_client_page(client_page, ref_line):
        messages.append("added to client page")
    else:
        logger.debug("Client page not found: %s", client_page)

    # 3 — DB writes
    with get_write_db() as db_w:
        db_w.execute(
            "UPDATE library_entries SET frequency = frequency + 1, updated_at = datetime('now') WHERE id = ?",
            (entry_id,),
        )
        db_w.execute(
            """
            INSERT INTO library_share_log (entry_id, client_id, meeting_date, actions_taken)
            VALUES (?, ?, ?, ?)
            """,
            (entry_id, body.client_id, meeting_date, '["record"]'),
        )
        db_w.commit()

    # 4 — Manifest Google Doc append (non-fatal; skipped silently if no URL)
    manifest_updated: bool = False
    manifest_skipped: bool = False  # True when URL is absent (no toast needed)
    manifest_url = client_row["manifest_gdoc_url"]

    if not manifest_url:
        manifest_skipped = True
        logger.debug(
            "Manifest append skipped for client %d (%s): manifest_gdoc_url not set",
            body.client_id, client_row["name"],
        )
    else:
        doc_id = _doc_id_from_url(manifest_url)
        if not doc_id:
            logger.warning(
                "Manifest append skipped for client %d: could not extract doc ID from %r",
                body.client_id, manifest_url,
            )
        else:
            # url_or_doc_link: webpage_url > amazon_url (books) > url
            url_or_doc_link = (
                entry_row["webpage_url"]
                or (entry_row["amazon_url"] if entry_row["type_code"] == "b" else None)
                or entry_row["url"]
                or ""
            )
            bullet = (
                f"{entry_row['name']} ({type_label})"
                + (f" — {url_or_doc_link}" if url_or_doc_link else "")
                + f" — {meeting_date}"
            )
            try:
                _append_to_manifest_others(doc_id, bullet)
                manifest_updated = True
                messages.append("appended to Manifest")
            except Exception as exc:
                logger.error(
                    "Manifest append failed for client %d entry %d: %s",
                    body.client_id, entry_id, exc,
                )
                messages.append(f"Manifest write failed: {exc}")

    logger.info(
        "Recorded entry %d (%s) for client %d (%s): %s",
        entry_id, entry_row["name"], body.client_id, client_row["name"], messages,
    )
    return {
        "status": "ok",
        "message": f"Recorded for {client_row['name']}",
        "details": messages,
        "manifest_updated": manifest_updated,
        "manifest_skipped": manifest_skipped,
        "entry_name": entry_row["name"],
    }


# ---------------------------------------------------------------------------
# HTML page templates
# ---------------------------------------------------------------------------

_BOOK_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <meta name="author" content="{author}">
</head>
<body>
  <h1>{title}</h1>
  <p><strong>Author:</strong> {author}</p>
  <p><strong>Topics:</strong> {topics}</p>
  {comments_block}
  {amazon_block}
</body>
</html>
"""

_GENERIC_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
</head>
<body>
  <h1>{title}</h1>
  {author_block}
  <p><strong>Topics:</strong> {topics}</p>
  {comments_block}
</body>
</html>
"""


def _slugify(name: str) -> str:
    """Lowercase, strip non-alphanumeric (keep spaces), collapse spaces to hyphens."""
    name = name.lower()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name.strip())
    return name


def _render_page(entry_row, author: str | None, topics: list[dict]) -> str:
    title = _html.escape(entry_row["name"])
    author_esc = _html.escape(author or "")
    topics_str = _html.escape(", ".join(t["code"] for t in topics)) if topics else ""
    comments_block = (
        f"<p>{_html.escape(entry_row['comments'])}</p>"
        if entry_row.get("comments")
        else ""
    )

    if entry_row["type_code"] == "b":
        amazon_block = (
            f'<p><a href="{_html.escape(entry_row["amazon_url"])}">Buy on Amazon</a></p>'
            if entry_row.get("amazon_url")
            else ""
        )
        return _BOOK_TEMPLATE.format(
            title=title,
            author=author_esc,
            topics=topics_str,
            comments_block=comments_block,
            amazon_block=amazon_block,
        )
    else:
        author_block = f"<p><strong>Author:</strong> {author_esc}</p>" if author_esc else ""
        return _GENERIC_TEMPLATE.format(
            title=title,
            author_block=author_block,
            topics=topics_str,
            comments_block=comments_block,
        )


# ---------------------------------------------------------------------------
# POST /api/libby/entries/{id}/action/make
# ---------------------------------------------------------------------------

@router.post("/entries/{entry_id}/action/make")
def action_make(entry_id: int):
    """Generate a GitHub Pages HTML file for this entry, push, and set webpage_url.

    If webpage_url is already set, returns the existing URL without regenerating.
    Requires LIBBY_GITHUB_REPO_PATH and LIBBY_BASE_URL in config.
    """
    from app_config import get_secret

    db_r = get_db()

    # --- Load entry with author ---
    entry_row = db_r.execute(
        """
        SELECT
            e.id, e.name, e.type_code, e.url, e.webpage_url, e.amazon_url,
            e.comments,
            COALESCE(lb.author, li.author) AS author
        FROM library_entries e
        LEFT JOIN library_books lb ON e.type_code = 'b' AND e.entity_id = lb.id
        LEFT JOIN library_items li ON e.type_code != 'b' AND e.entity_id = li.id
        WHERE e.id = ?
        """,
        (entry_id,),
    ).fetchone()
    if not entry_row:
        raise HTTPException(status_code=404, detail="Entry not found")

    # --- Already has a page ---
    if entry_row["webpage_url"]:
        return {"status": "exists", "url": entry_row["webpage_url"]}

    # --- Config check ---
    repo_path_str = get_secret("LIBBY_GITHUB_REPO_PATH")
    base_url = (get_secret("LIBBY_BASE_URL") or "").rstrip("/")
    if not repo_path_str:
        return {"status": "error", "message": "GitHub Pages repo not configured"}
    if not base_url:
        return {"status": "error", "message": "LIBBY_BASE_URL not configured"}

    repo_path = Path(repo_path_str).expanduser()
    if not repo_path.is_dir():
        return {"status": "error", "message": f"GitHub Pages repo path does not exist: {repo_path}"}

    # --- Load topics ---
    topics = [
        {"code": r["code"], "name": r["name"]}
        for r in db_r.execute(
            """
            SELECT lt.code, lt.name
            FROM library_entry_topics jet
            JOIN library_topics lt ON jet.topic_id = lt.id
            WHERE jet.entry_id = ?
            """,
            (entry_id,),
        ).fetchall()
    ]

    # --- Build slug and paths ---
    slug = _slugify(entry_row["name"])
    type_code = entry_row["type_code"]
    rel_path = Path("library") / type_code / f"{slug}.html"
    out_path = repo_path / rel_path
    public_url = f"{base_url}/library/{type_code}/{slug}.html"

    # --- Render HTML ---
    html_content = _render_page(entry_row, entry_row["author"], topics)

    # --- Write file ---
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_content, encoding="utf-8")

    # --- Git add / commit / push ---
    try:
        subprocess.run(
            ["git", "-C", str(repo_path), "add", "-A"],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_path), "commit", "-m", f"libby: {slug}"],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_path), "push"],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.error("git operation failed for libby make: %s", exc.stderr)
        raise HTTPException(
            status_code=500,
            detail=f"git error: {exc.stderr.strip()}",
        )

    # --- Persist webpage_url ---
    with get_write_db() as db_w:
        db_w.execute(
            "UPDATE library_entries SET webpage_url = ?, updated_at = datetime('now') WHERE id = ?",
            (public_url, entry_id),
        )
        db_w.commit()

    logger.info("make: created page for entry %d at %s", entry_id, public_url)
    return {"status": "created", "url": public_url}


# ---------------------------------------------------------------------------
# Topics CRUD  (Items 5)
# GET  /api/libby/topics
# POST /api/libby/topics/merge          ← must precede /{id} to avoid int parse
# PUT  /api/libby/topics/{id}
# DELETE /api/libby/topics/{id}
# ---------------------------------------------------------------------------

@router.get("/topics")
def get_topics():
    """Return all topics with their entry counts."""
    db = get_db()
    rows = db.execute(
        """SELECT t.id, t.code, t.name,
                  COUNT(et.entry_id) AS entry_count
           FROM library_topics t
           LEFT JOIN library_entry_topics et ON et.topic_id = t.id
           GROUP BY t.id
           ORDER BY t.code""",
    ).fetchall()
    return {"topics": [dict(r) for r in rows]}


class TopicCreateRequest(BaseModel):
    code: str
    name: str


@router.post("/topics")
def create_topic(body: TopicCreateRequest):
    """Create a new topic."""
    code = body.code.strip().lower()
    name = body.name.strip()
    if not code or len(code) > 4:
        raise HTTPException(status_code=400, detail="Code must be 1–4 characters")
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    db = get_db()
    existing = db.execute("SELECT id FROM library_topics WHERE code = ?", (code,)).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail=f"Code '{code}' already in use")

    with get_write_db() as dbw:
        cur = dbw.execute(
            "INSERT INTO library_topics (code, name) VALUES (?, ?)", (code, name)
        )
        dbw.commit()
        new_id = cur.lastrowid
    return {"id": new_id, "code": code, "name": name, "entry_count": 0}


class TopicUpdateRequest(BaseModel):
    code: str | None = None
    name: str | None = None


@router.put("/topics/{topic_id}")
def update_topic(topic_id: int, body: TopicUpdateRequest):
    """Update a topic's code and/or name."""
    db = get_db()
    row = db.execute("SELECT id, code, name FROM library_topics WHERE id = ?", (topic_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Topic not found")

    new_code = (body.code or "").strip() or row["code"]
    new_name = (body.name or "").strip() or row["name"]

    if new_code != row["code"]:
        existing = db.execute(
            "SELECT id FROM library_topics WHERE code = ? AND id != ?", (new_code, topic_id)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Topic code '{new_code}' already exists")

    with get_write_db() as dbw:
        dbw.execute(
            "UPDATE library_topics SET code = ?, name = ? WHERE id = ?",
            (new_code, new_name, topic_id),
        )
        dbw.commit()
    return {"status": "ok", "id": topic_id, "code": new_code, "name": new_name}


@router.delete("/topics/{topic_id}")
def delete_topic(topic_id: int):
    """Delete a topic — only allowed if no entries are assigned to it."""
    db = get_db()
    row = db.execute("SELECT id, code, name FROM library_topics WHERE id = ?", (topic_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Topic not found")

    count = db.execute(
        "SELECT COUNT(*) AS cnt FROM library_entry_topics WHERE topic_id = ?", (topic_id,)
    ).fetchone()["cnt"]
    if count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete topic '{row['code']}': {count} entr{'y' if count == 1 else 'ies'} assigned",
        )

    with get_write_db() as dbw:
        dbw.execute("DELETE FROM library_topics WHERE id = ?", (topic_id,))
        dbw.commit()
    return {"status": "ok"}


class TopicMergeRequest(BaseModel):
    source_id: int
    target_id: int


@router.post("/topics/merge")
def merge_topics(body: TopicMergeRequest):
    """Reassign all entries from source topic to target topic, then delete source."""
    db = get_db()
    if body.source_id == body.target_id:
        raise HTTPException(status_code=400, detail="Source and target must differ")

    source = db.execute("SELECT id, code, name FROM library_topics WHERE id = ?", (body.source_id,)).fetchone()
    target = db.execute("SELECT id, code, name FROM library_topics WHERE id = ?", (body.target_id,)).fetchone()
    if not source:
        raise HTTPException(status_code=404, detail="Source topic not found")
    if not target:
        raise HTTPException(status_code=404, detail="Target topic not found")

    with get_write_db() as dbw:
        # Re-point entries that don't already have the target topic
        dbw.execute(
            """UPDATE library_entry_topics SET topic_id = ?
               WHERE topic_id = ?
                 AND entry_id NOT IN (
                     SELECT entry_id FROM library_entry_topics WHERE topic_id = ?
                 )""",
            (body.target_id, body.source_id, body.target_id),
        )
        # Delete any remaining source rows (duplicates now covered by target)
        dbw.execute("DELETE FROM library_entry_topics WHERE topic_id = ?", (body.source_id,))
        dbw.execute("DELETE FROM library_topics WHERE id = ?", (body.source_id,))
        dbw.commit()

    moved = db.execute(
        "SELECT COUNT(*) AS cnt FROM library_entry_topics WHERE topic_id = ?", (body.target_id,)
    ).fetchone()["cnt"]
    return {"status": "ok", "source": source["code"], "target": target["code"], "entries_in_target": moved}


# ---------------------------------------------------------------------------
# Entry–topic assignment
# POST   /api/libby/entries/{entry_id}/topics/{topic_id}
# DELETE /api/libby/entries/{entry_id}/topics/{topic_id}
# ---------------------------------------------------------------------------

@router.post("/entries/{entry_id}/topics/{topic_id}")
def add_entry_topic(entry_id: int, topic_id: int):
    """Assign a topic to an entry (idempotent)."""
    db = get_db()
    entry = db.execute("SELECT id FROM library_entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    topic = db.execute("SELECT id, name FROM library_topics WHERE id = ?", (topic_id,)).fetchone()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    with get_write_db() as dbw:
        dbw.execute(
            "INSERT OR IGNORE INTO library_entry_topics (entry_id, topic_id) VALUES (?, ?)",
            (entry_id, topic_id),
        )
        dbw.commit()
    return {"action": "added", "topic_name": topic["name"]}


@router.delete("/entries/{entry_id}/topics/{topic_id}")
def remove_entry_topic(entry_id: int, topic_id: int):
    """Remove a topic from an entry."""
    db = get_db()
    topic = db.execute("SELECT id, name FROM library_topics WHERE id = ?", (topic_id,)).fetchone()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    with get_write_db() as dbw:
        dbw.execute(
            "DELETE FROM library_entry_topics WHERE entry_id = ? AND topic_id = ?",
            (entry_id, topic_id),
        )
        dbw.commit()
    return {"action": "removed", "topic_name": topic["name"]}


# ---------------------------------------------------------------------------
# PUT /api/libby/entries/{id} — update entry fields
# ---------------------------------------------------------------------------

def _fetch_entry_dict(db, entry_id: int) -> dict:
    """Fetch a single entry in the same schema as search results."""
    import json as _json

    row = db.execute(
        """
        SELECT
            e.id, e.name, e.type_code, e.priority, e.frequency,
            e.url, e.amazon_url, e.amazon_short_url, e.webpage_url,
            e.gdoc_id, e.comments, e.obsidian_link, e.private,
            lb.categories,
            COALESCE(lb.author, li.author) AS author,
            lb.year, lb.isbn, lb.subtitle, lb.preview_link,
            li.publication, li.published_date,
            li.show_name, li.episode, li.host,
            li.text AS quote_text, li.attribution, li.context,
            li.notes AS synopsis
        FROM library_entries e
        LEFT JOIN library_books lb ON e.type_code = 'b' AND e.entity_id = lb.id
        LEFT JOIN library_items li ON e.type_code != 'b' AND e.entity_id = li.id
        WHERE e.id = ?
        """,
        (entry_id,),
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Entry not found")

    def _quote_author(comments: str | None) -> str | None:
        if not comments:
            return None
        idx = comments.find(" \u2014 ")
        if idx < 0:
            return None
        return comments[idx + 3:].strip() or None

    author = row["author"] or (
        _quote_author(row["comments"]) if row["type_code"] == "q" else None
    )
    categories: list[str] = []
    if row["categories"]:
        try:
            categories = _json.loads(row["categories"])
        except Exception:
            pass

    topics = [
        {"id": tr["topic_id"], "code": tr["code"], "name": tr["name"]}
        for tr in db.execute(
            """SELECT jet.entry_id, lt.id AS topic_id, lt.code, lt.name
               FROM library_entry_topics jet
               JOIN library_topics lt ON jet.topic_id = lt.id
               WHERE jet.entry_id = ?""",
            (entry_id,),
        ).fetchall()
    ]

    return {
        "id": row["id"],
        "name": row["name"],
        "type_code": row["type_code"],
        "priority": row["priority"],
        "frequency": row["frequency"],
        "url": row["url"],
        "amazon_url": row["amazon_url"],
        "amazon_short_url": row["amazon_short_url"],
        "webpage_url": row["webpage_url"],
        "gdoc_id": row["gdoc_id"],
        "obsidian_link": row["obsidian_link"],
        "author": author,
        "author_match": False,
        "description": row["comments"] or None,
        "categories": categories,
        "topics": topics,
        "year": row["year"],
        "isbn": row["isbn"],
        "subtitle": row["subtitle"],
        "preview_link": row["preview_link"],
        "publication": row["publication"],
        "published_date": row["published_date"],
        "show_name": row["show_name"],
        "episode": row["episode"],
        "host": row["host"],
        "quote_text": row["quote_text"],
        "attribution": row["attribution"],
        "context": row["context"],
        "synopsis": row["synopsis"],
        "private": bool(row["private"]),
        "last_shared_at": None,
    }


class EntryUpdateRequest(BaseModel):
    name: str | None = None
    comments: str | None = None
    priority: str | None = None
    url: str | None = None
    topic_ids: list[int] | None = None
    # Book fields
    author: str | None = None
    year: int | None = None
    isbn: str | None = None
    # Non-book item fields
    publication: str | None = None
    published_date: str | None = None
    synopsis: str | None = None
    # Quote fields
    text: str | None = None
    attribution: str | None = None
    context: str | None = None
    # Worksheet / Assessment
    gdoc_id: str | None = None
    # Privacy flag
    private: bool | None = None


@router.put("/entries/{entry_id}")
def update_entry(entry_id: int, body: EntryUpdateRequest):
    """Update a library entry's fields.

    Updates library_entries master fields (name, comments, priority, url, gdoc_id),
    type-specific fields in library_books or library_items, and replaces the full
    topic set if topic_ids is provided. Returns the updated entry in search-result
    schema.
    """
    if body.priority is not None and body.priority not in ("high", "medium", "low"):
        raise HTTPException(status_code=400, detail="Priority must be high, medium, or low")

    db = get_db()
    entry = db.execute(
        "SELECT id, type_code, entity_id FROM library_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    tc = entry["type_code"]
    entity_id = entry["entity_id"]

    with get_write_db() as dbw:
        # --- library_entries master fields ---
        entry_fields: list[tuple[str, object]] = []
        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="Name cannot be empty")
            entry_fields.append(("name", name))
        if body.comments is not None:
            entry_fields.append(("comments", body.comments.strip() or None))
        if body.priority is not None:
            entry_fields.append(("priority", body.priority))
        if body.url is not None:
            entry_fields.append(("url", body.url.strip() or None))
        if body.gdoc_id is not None:
            entry_fields.append(("gdoc_id", body.gdoc_id.strip() or None))
        if body.private is not None:
            entry_fields.append(("private", int(body.private)))

        if entry_fields:
            set_clause = ", ".join(f"{col} = ?" for col, _ in entry_fields)
            values = [v for _, v in entry_fields]
            dbw.execute(
                f"UPDATE library_entries SET {set_clause}, updated_at = datetime('now') WHERE id = ?",  # noqa: S608
                values + [entry_id],
            )

        # --- Type-specific fields ---
        if tc == "b":
            book_fields: list[tuple[str, object]] = []
            if body.author is not None:
                book_fields.append(("author", body.author.strip() or None))
            if body.year is not None:
                book_fields.append(("year", body.year))
            if body.isbn is not None:
                book_fields.append(("isbn", body.isbn.strip() or None))
            if book_fields:
                set_clause = ", ".join(f"{col} = ?" for col, _ in book_fields)
                values = [v for _, v in book_fields]
                dbw.execute(
                    f"UPDATE library_books SET {set_clause} WHERE id = ?",  # noqa: S608
                    values + [entity_id],
                )
        else:
            item_fields: list[tuple[str, object]] = []
            if body.author is not None:
                item_fields.append(("author", body.author.strip() or None))
            if body.publication is not None:
                item_fields.append(("publication", body.publication.strip() or None))
            if body.published_date is not None:
                item_fields.append(("published_date", body.published_date.strip() or None))
            if body.synopsis is not None:
                item_fields.append(("notes", body.synopsis.strip() or None))
            if body.text is not None:
                item_fields.append(("text", body.text.strip() or None))
            if body.attribution is not None:
                item_fields.append(("attribution", body.attribution.strip() or None))
            if body.context is not None:
                item_fields.append(("context", body.context.strip() or None))
            if item_fields:
                set_clause = ", ".join(f"{col} = ?" for col, _ in item_fields)
                values = [v for _, v in item_fields]
                dbw.execute(
                    f"UPDATE library_items SET {set_clause} WHERE id = ?",  # noqa: S608
                    values + [entity_id],
                )

        # --- Topics: full replace ---
        if body.topic_ids is not None:
            dbw.execute(
                "DELETE FROM library_entry_topics WHERE entry_id = ?",
                (entry_id,),
            )
            if body.topic_ids:
                valid_ids = {
                    r["id"] for r in db.execute("SELECT id FROM library_topics").fetchall()
                }
                for tid in body.topic_ids:
                    if tid in valid_ids:
                        dbw.execute(
                            "INSERT OR IGNORE INTO library_entry_topics (entry_id, topic_id) VALUES (?, ?)",
                            (entry_id, tid),
                        )

        dbw.commit()

    # Re-fetch and return updated entry in search-result schema
    updated_db = get_db()
    return _fetch_entry_dict(updated_db, entry_id)


# ---------------------------------------------------------------------------
# DELETE /api/libby/entries/{id} — permanently delete an entry
# ---------------------------------------------------------------------------

@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int):
    """Delete a library entry and its type-specific entity row.

    Removes in FK-safe order: topics, share log, enrich-not-found log,
    the master library_entries row, then the type-specific entity row
    (library_books or library_items). Does not touch any external systems.
    """
    db = get_db()
    row = db.execute(
        "SELECT id, name, entity_id, type_code FROM library_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Entry not found")

    entry_name = row["name"]
    entity_id  = row["entity_id"]
    tc         = row["type_code"]

    with get_write_db() as dbw:
        dbw.execute("DELETE FROM library_entry_topics WHERE entry_id = ?", (entry_id,))
        dbw.execute("DELETE FROM library_share_log WHERE entry_id = ?",    (entry_id,))
        dbw.execute("DELETE FROM library_enrich_not_found WHERE entry_id = ?", (entry_id,))
        dbw.execute("DELETE FROM library_entries WHERE id = ?", (entry_id,))
        if tc == "b":
            dbw.execute("DELETE FROM library_books WHERE id = ?",  (entity_id,))
        else:
            dbw.execute("DELETE FROM library_items WHERE id = ?",  (entity_id,))
        dbw.commit()

    return {"deleted": True, "name": entry_name}


# ---------------------------------------------------------------------------
# Retype — change entry's type
# POST /api/libby/entries/{id}/retype
# ---------------------------------------------------------------------------

class RetypeRequest(BaseModel):
    new_type_code: str


@router.post("/entries/{entry_id}/retype")
def retype_entry(entry_id: int, body: RetypeRequest):
    """Change an entry's type code. Creates a fresh row in the new type table,
    updates library_entries, and removes the old type-specific row.
    Master fields (name, url, topics, priority) are preserved.
    Type-specific fields are not migrated (schemas differ).
    """
    new_code = body.new_type_code.strip().lower()
    db = get_db()

    # Validate new type exists
    new_type = db.execute(
        "SELECT code, name, table_name FROM library_types WHERE code = ?", (new_code,)
    ).fetchone()
    if not new_type:
        raise HTTPException(status_code=400, detail=f"Unknown type code: '{new_code}'")

    # Get current entry
    entry = db.execute(
        "SELECT id, name, type_code, entity_id FROM library_entries WHERE id = ?", (entry_id,)
    ).fetchone()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    old_code = entry["type_code"]
    old_entity_id = entry["entity_id"]

    if old_code == new_code:
        raise HTTPException(status_code=400, detail=f"Entry is already type '{new_code}'")

    new_table = new_type["table_name"]

    with get_write_db() as dbw:
        if old_code != 'b' and new_code != 'b':
            # Non-book → non-book: both map to library_items, entity_id stays the same.
            # Just update the type_code — no insert/delete needed.
            dbw.execute(
                "UPDATE library_entries SET type_code = ? WHERE id = ?",
                (new_code, entry_id),
            )
        else:
            # Involves a book type (blocked by UI, but handle defensively):
            # Insert a fresh row in the new table and clean up the old one.
            cur = dbw.execute(f"INSERT INTO {new_table} (id) VALUES (NULL)")  # noqa: S608
            new_entity_id = cur.lastrowid
            dbw.execute(
                "UPDATE library_entries SET type_code = ?, entity_id = ? WHERE id = ?",
                (new_code, new_entity_id, entry_id),
            )
            old_type = db.execute(
                "SELECT table_name FROM library_types WHERE code = ?", (old_code,)
            ).fetchone()
            if old_type and old_entity_id is not None:
                old_table = old_type["table_name"]
                dbw.execute(f"DELETE FROM {old_table} WHERE id = ?", (old_entity_id,))  # noqa: S608

        dbw.commit()

    return {
        "old_type": old_code,
        "new_type": new_code,
        "entry_name": entry["name"],
    }


# ---------------------------------------------------------------------------
# Types CRUD  (Item 6)
# GET  /api/libby/types
# PUT  /api/libby/types/{code}
# POST /api/libby/types
# ---------------------------------------------------------------------------

@router.get("/types")
def get_types():
    """Return all types with their entry counts."""
    db = get_db()
    rows = db.execute(
        """SELECT t.code, t.name, t.description, t.table_name,
                  COUNT(e.id) AS entry_count
           FROM library_types t
           LEFT JOIN library_entries e ON e.type_code = t.code
           GROUP BY t.code
           ORDER BY t.code""",
    ).fetchall()
    return {"types": [dict(r) for r in rows]}


class TypeUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@router.put("/types/{code}")
def update_type(code: str, body: TypeUpdateRequest):
    """Update a type's name and/or description."""
    db = get_db()
    row = db.execute("SELECT code, name, description FROM library_types WHERE code = ?", (code,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Type not found")

    new_name = (body.name or "").strip() or row["name"]
    new_desc = body.description  # allow clearing to empty string

    with get_write_db() as dbw:
        dbw.execute(
            "UPDATE library_types SET name = ?, description = ? WHERE code = ?",
            (new_name, new_desc, code),
        )
        dbw.commit()
    return {"status": "ok", "code": code, "name": new_name, "description": new_desc}


class TypeCreateRequest(BaseModel):
    code: str
    name: str
    description: str | None = None


@router.post("/types")
def create_type(body: TypeCreateRequest):
    """Add a new entry type. Code must be a unique single letter not already in use."""
    code = body.code.strip().lower()
    name = body.name.strip()
    if not code or len(code) != 1 or not code.isalpha():
        raise HTTPException(status_code=400, detail="Type code must be a single letter")
    if not name:
        raise HTTPException(status_code=400, detail="Type name is required")

    db = get_db()
    existing = db.execute("SELECT code FROM library_types WHERE code = ?", (code,)).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail=f"Type code '{code}' already exists")

    # table_name follows the pattern library_{plural}; use a safe default
    table_name = f"library_{code}_entries"

    with get_write_db() as dbw:
        dbw.execute(
            "INSERT INTO library_types (code, name, description, table_name) VALUES (?, ?, ?, ?)",
            (code, name, body.description, table_name),
        )
        dbw.commit()
    return {"status": "ok", "code": code, "name": name, "description": body.description}


# ---------------------------------------------------------------------------
# GET  /api/libby/queue  — entries awaiting enrichment (needs_enrichment = 1)
# POST /api/libby/entries — create a new library entry
# ---------------------------------------------------------------------------

@router.get("/queue")
def get_queue():
    """Return all library entries pending enrichment, with current status.

    Status is derived from libby_enrichment_log:
      pending    — no log rows yet (just created)
      processing — any row in 'processing' state
      ready      — all rows complete (needs_enrichment should be 0 by then)
      failed     — any row in 'failed' state
    For now returns 'pending' for everything until Items 3/4 are implemented.
    """
    db = get_db()
    rows = db.execute(
        """
        SELECT e.id, e.name, e.type_code, e.created_at,
               COALESCE(
                 CASE
                   WHEN SUM(CASE WHEN el.status = 'failed'     THEN 1 ELSE 0 END) > 0 THEN 'failed'
                   WHEN SUM(CASE WHEN el.status = 'processing' THEN 1 ELSE 0 END) > 0 THEN 'processing'
                   WHEN COUNT(el.id) > 0
                    AND SUM(CASE WHEN el.status = 'complete'   THEN 1 ELSE 0 END) = COUNT(el.id)
                        THEN 'ready'
                   ELSE 'pending'
                 END,
                 'pending'
               ) AS status
        FROM library_entries e
        LEFT JOIN libby_enrichment_log el ON el.entry_id = e.id
        WHERE e.needs_enrichment = 1
        GROUP BY e.id
        ORDER BY e.created_at DESC
        """
    ).fetchall()
    entries = [
        {
            "id": r["id"],
            "name": r["name"],
            "type_code": r["type_code"],
            "created_at": r["created_at"],
            "status": r["status"],
        }
        for r in rows
    ]
    return {"entries": entries, "count": len(entries)}


class EntryCreateRequest(BaseModel):
    name: str
    type_code: str
    url: str | None = None
    comments: str | None = None
    priority: str = "medium"
    # Extra fields written to library_items (non-book types only)
    author: str | None = None
    item_text: str | None = None      # stored in library_items.text
    attribution: str | None = None    # stored in library_items.attribution


@router.post("/entries")
def create_entry(body: EntryCreateRequest, background_tasks: BackgroundTasks):
    """Create a new library entry with the generic common fields.

    Inserts a minimal row into the type-specific entity table, then inserts
    into library_entries. Sets needs_enrichment = 1. Returns new entry id.
    """
    name = body.name.strip()
    type_code = body.type_code.lower().strip()

    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if type_code not in _VALID_TYPE_CODES:
        raise HTTPException(status_code=400, detail=f"Unknown type code: {type_code!r}")
    if body.priority not in ("high", "medium", "low"):
        raise HTTPException(status_code=400, detail="Priority must be high, medium, or low")

    db = get_db()
    type_row = db.execute(
        "SELECT table_name FROM library_types WHERE code = ?", (type_code,)
    ).fetchone()
    if not type_row:
        raise HTTPException(status_code=400, detail=f"Type '{type_code}' not registered in library_types")

    table_name = type_row["table_name"]

    with get_write_db() as dbw:
        # Minimal entity row (id only)
        entity_cursor = dbw.execute(f"INSERT INTO {table_name} (id) VALUES (NULL)")
        entity_id = entity_cursor.lastrowid

        # For library_items, populate optional metadata fields if provided
        if table_name == "library_items" and (body.author or body.item_text or body.attribution):
            dbw.execute(
                "UPDATE library_items SET author = ?, text = ?, attribution = ? WHERE id = ?",
                (body.author or None, body.item_text or None, body.attribution or None, entity_id),
            )

        # Main entry row
        entry_cursor = dbw.execute(
            """INSERT INTO library_entries
               (name, type_code, url, comments, priority, entity_id,
                needs_enrichment, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))""",
            (name, type_code, body.url or None, body.comments or None, body.priority, entity_id),
        )
        entry_id = entry_cursor.lastrowid
        dbw.commit()

    _create_vault_home_page(
        entry_id=entry_id,
        type_code=type_code,
        name=name,
        url=body.url,
        comments=body.comments,
        priority=body.priority,
    )
    _invalidate_type_counts_cache()
    background_tasks.add_task(_run_tagging_task, entry_id)
    logger.info("Created library entry %d: %r (%s)", entry_id, name, type_code)
    return {"id": entry_id, "status": "created", "name": name, "type_code": type_code}


# ---------------------------------------------------------------------------
# GET /api/libby/books/lookup — Google Books API metadata lookup
# POST /api/libby/books — create a fully-specified book entry
# ---------------------------------------------------------------------------

_ASIN_RE = re.compile(r"(?:dp|gp/product)/([A-Z0-9]{10})")


def _extract_asin(url: str) -> str | None:
    m = _ASIN_RE.search(url)
    return m.group(1) if m else None


def _google_books_search(params: dict) -> list[dict]:
    """Query Google Books API and return up to 5 structured candidates."""
    import httpx
    try:
        resp = httpx.get(
            "https://www.googleapis.com/books/v1/volumes",
            params=params,
            timeout=8.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Google Books API error: %s", exc)
        return []

    candidates = []
    for item in data.get("items", [])[:5]:
        info = item.get("volumeInfo", {})
        isbns = {id_["type"]: id_["identifier"] for id_ in info.get("industryIdentifiers", [])}
        isbn = isbns.get("ISBN_13") or isbns.get("ISBN_10")
        desc = info.get("description", "")
        candidates.append({
            "google_books_id": item.get("id"),
            "title": info.get("title", ""),
            "author": ", ".join(info.get("authors", [])),
            "isbn": isbn,
            "publisher": info.get("publisher"),
            "year": str(info.get("publishedDate", ""))[:4] or None,
            "description": desc[:500] if desc else None,
            "cover_url": info.get("imageLinks", {}).get("thumbnail"),
            "page_count": info.get("pageCount"),
        })
    return candidates


@router.get("/books/lookup")
def lookup_book(
    title: str | None = None,
    author: str | None = None,
    asin: str | None = None,
    url: str | None = None,
):
    """Look up book metadata from the Google Books API.

    Accepts one of:
      - title and/or author → full-text search
      - asin → search by ISBN derived from ASIN (best-effort) or title fallback
      - url → extract ASIN from Amazon URL, then look up

    Returns up to 5 candidate results.
    """
    # Resolve ASIN from URL if provided
    if url and not asin:
        asin = _extract_asin(url)

    if asin:
        # ISBN-10 and ASIN share the same format; try ISBN lookup first
        params: dict = {"q": f"isbn:{asin}", "maxResults": 5}
        candidates = _google_books_search(params)
        if not candidates and title:
            # Fallback: title search
            params = {"q": f"intitle:{title}", "maxResults": 5}
            candidates = _google_books_search(params)
        # Construct Amazon URL from ASIN
        amazon_url = f"https://www.amazon.com/dp/{asin}"
        for c in candidates:
            c["asin"] = asin
            c["amazon_url"] = amazon_url
    elif title or author:
        q_parts = []
        if title:
            q_parts.append(f"intitle:{title}")
        if author:
            q_parts.append(f"inauthor:{author}")
        params = {"q": "+".join(q_parts), "maxResults": 5}
        candidates = _google_books_search(params)
        for c in candidates:
            c["asin"] = None
            c["amazon_url"] = None
    else:
        raise HTTPException(status_code=400, detail="Provide title, author, asin, or url")

    return {"candidates": candidates}


class BookCreateRequest(BaseModel):
    name: str
    author: str | None = None
    isbn: str | None = None
    publisher: str | None = None
    year: str | None = None
    url: str | None = None          # canonical URL (tinyurl or other)
    amazon_url: str | None = None
    cover_url: str | None = None
    google_books_id: str | None = None
    subtitle: str | None = None
    categories: list[str] = []
    preview_link: str | None = None
    authors: list[str] = []
    comments: str | None = None
    priority: str = "medium"
    topic_ids: list[int] = []
    status: str = "unread"


@router.post("/books")
def create_book(body: BookCreateRequest, background_tasks: BackgroundTasks):
    """Create a fully-specified book entry (used by the book creation form).

    Inserts into library_books with all provided fields, creates the
    library_entries row, assigns topics, sets needs_enrichment=1.
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if body.priority not in ("high", "medium", "low"):
        raise HTTPException(status_code=400, detail="Priority must be high, medium, or low")

    year_int: int | None = None
    if body.year:
        try:
            year_int = int(body.year[:4])
        except (ValueError, TypeError):
            pass

    db = get_db()

    import json as _json
    with get_write_db() as dbw:
        # Book entity row
        book_cursor = dbw.execute(
            """INSERT INTO library_books
               (author, isbn, publisher, year, cover_url, google_books_id,
                subtitle, categories, preview_link, authors, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.author, body.isbn, body.publisher, year_int,
             body.cover_url, body.google_books_id,
             body.subtitle or None,
             _json.dumps(body.categories) if body.categories else None,
             body.preview_link or None,
             _json.dumps(body.authors) if body.authors else None,
             body.status or "unread"),
        )
        book_id = book_cursor.lastrowid

        # Library entry row
        entry_cursor = dbw.execute(
            """INSERT INTO library_entries
               (name, type_code, url, amazon_url, comments, priority, entity_id,
                needs_enrichment, created_at, updated_at)
               VALUES (?, 'b', ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))""",
            (name, body.url or None, body.amazon_url or None,
             body.comments or None, body.priority, book_id),
        )
        entry_id = entry_cursor.lastrowid

        # Assign topics
        if body.topic_ids:
            all_topic_ids = {
                r["id"] for r in db.execute("SELECT id FROM library_topics").fetchall()
            }
            for tid in body.topic_ids:
                if tid in all_topic_ids:
                    dbw.execute(
                        "INSERT OR IGNORE INTO library_entry_topics (entry_id, topic_id) VALUES (?, ?)",
                        (entry_id, tid),
                    )

        dbw.commit()

    _create_vault_home_page(
        entry_id=entry_id,
        type_code="b",
        name=name,
        author=body.author,
        url=body.url,
        amazon_url=body.amazon_url,
        comments=body.comments,
        priority=body.priority,
        isbn=body.isbn or None,
        publisher=body.publisher or None,
        year=body.year or None,
        status=body.status or "unread",
        subtitle=body.subtitle or None,
        categories=body.categories or None,
        authors=body.authors or None,
    )
    _invalidate_type_counts_cache()
    background_tasks.add_task(_run_tagging_task, entry_id)
    logger.info("Created book entry %d: %r", entry_id, name)
    return {"id": entry_id, "status": "created", "name": name, "type_code": "b"}


# ---------------------------------------------------------------------------
# POST /api/libby/fetch-metadata — URL metadata extraction
# ---------------------------------------------------------------------------

class FetchMetadataRequest(BaseModel):
    url: str


@router.post("/fetch-metadata")
def fetch_metadata(body: FetchMetadataRequest):
    """Fetch a URL and extract Open Graph metadata (title, description, author).

    For YouTube URLs, uses the oEmbed API for richer metadata.
    Returns: title, author, description, site_name — all optional strings.
    """
    import re as _re

    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # YouTube oEmbed — richer and more reliable than scraping
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
                    "site_name": "YouTube",
                }
        except Exception as exc:
            logger.warning("YouTube oEmbed failed for %s: %s", url, exc)

    # General fetch + og: tag extraction
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
        logger.warning("Fetch failed for %s: %s", url, exc)
        raise HTTPException(status_code=422, detail=f"Could not fetch URL: {exc}")

    def _og(prop: str) -> str | None:
        m = _re.search(
            rf'<meta[^>]+property=["\']og:{_re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
            html_text, _re.IGNORECASE,
        ) or _re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:{_re.escape(prop)}["\']',
            html_text, _re.IGNORECASE,
        )
        return _html.unescape(m.group(1)).strip() if m else None

    def _meta_name(name: str) -> str | None:
        m = _re.search(
            rf'<meta[^>]+name=["\']({_re.escape(name)})["\'][^>]+content=["\']([^"\']+)["\']',
            html_text, _re.IGNORECASE,
        ) or _re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']({_re.escape(name)})["\']',
            html_text, _re.IGNORECASE,
        )
        return _html.unescape(m.group(2)).strip() if m else None

    def _title_tag() -> str | None:
        m = _re.search(r'<title[^>]*>([^<]+)</title>', html_text, _re.IGNORECASE)
        return _html.unescape(m.group(1)).strip() if m else None

    title = _og("title") or _meta_name("title") or _title_tag()
    description = _og("description") or _meta_name("description")
    author = _og("article:author") or _meta_name("author")
    site_name = _og("site_name")

    return {
        "title": title,
        "author": author,
        "description": description,
        "site_name": site_name,
    }


# ---------------------------------------------------------------------------
# GET /api/libby/movies/lookup — OMDB movie search
# ---------------------------------------------------------------------------

@router.get("/movies/lookup")
def lookup_movie(title: str):
    """Search OMDB for movies matching the given title.

    Returns up to 5 candidates with title, year, poster, and imdb_id.
    """
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title is required")

    try:
        resp = httpx.get(
            "https://www.omdbapi.com/",
            params={"s": title.strip(), "type": "movie", "apikey": "trilogy"},
            timeout=8.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("OMDB API error: %s", exc)
        raise HTTPException(status_code=502, detail="OMDB lookup failed")

    if data.get("Response") == "False":
        return {"candidates": []}

    candidates = []
    for item in (data.get("Search") or [])[:5]:
        candidates.append({
            "title": item.get("Title"),
            "year": item.get("Year"),
            "poster": item.get("Poster") if item.get("Poster") != "N/A" else None,
            "imdb_id": item.get("imdbID"),
        })

    return {"candidates": candidates}


# ---------------------------------------------------------------------------
# Background task: auto-tagging via Claude API  (Item 3)
# ---------------------------------------------------------------------------

def _run_tagging_task(entry_id: int) -> None:
    """Auto-tag a library entry using Claude.

    Loads all topics from library_topics, calls claude-sonnet-4-6 with the
    entry metadata, parses the returned JSON array of topic IDs, inserts
    matched rows into library_entry_topics, and records completion status
    in libby_enrichment_log.

    Runs as a FastAPI BackgroundTask after POST /api/libby/entries or
    POST /api/libby/books.
    """
    import json
    import anthropic

    db = get_db()

    # Load entry with author (books / articles)
    entry_row = db.execute(
        """
        SELECT e.id, e.name, e.type_code, e.url, e.comments,
               COALESCE(lb.author, li.author) AS author
        FROM library_entries e
        LEFT JOIN library_books lb ON e.type_code = 'b' AND e.entity_id = lb.id
        LEFT JOIN library_items li ON e.type_code != 'b' AND e.entity_id = li.id
        WHERE e.id = ?
        """,
        (entry_id,),
    ).fetchone()

    if not entry_row:
        logger.error("Tagging task: entry %d not found", entry_id)
        return

    # Load all topics
    topic_rows = db.execute(
        "SELECT id, code, name FROM library_topics ORDER BY code"
    ).fetchall()
    if not topic_rows:
        logger.info("Tagging task: no topics defined, skipping entry %d", entry_id)
        return

    topics_list = "\n".join(
        f"  {r['id']}: {r['code']} — {r['name']}" for r in topic_rows
    )

    type_name = _TYPE_NAMES.get(entry_row["type_code"], entry_row["type_code"])
    desc_lines = [
        f"Name: {entry_row['name']}",
        f"Type: {type_name}",
    ]
    if entry_row["author"]:
        desc_lines.append(f"Author: {entry_row['author']}")
    if entry_row["url"]:
        desc_lines.append(f"URL: {entry_row['url']}")
    if entry_row["comments"]:
        desc_lines.append(f"Notes: {entry_row['comments']}")
    resource_text = "\n".join(desc_lines)

    prompt = (
        "You are a librarian assistant. Select the most relevant topic IDs for "
        "this resource from the list below.\n\n"
        f"Resource:\n{resource_text}\n\n"
        f"Available topics (id: code — name):\n{topics_list}\n\n"
        "Return ONLY a JSON array of integer topic IDs that apply, e.g. [1, 5, 12]. "
        "Return [] if none apply. No explanation, no markdown, just the JSON array."
    )

    # Mark as processing in enrichment log
    with get_write_db() as dbw:
        dbw.execute(
            """INSERT INTO libby_enrichment_log
               (entry_id, task, status, created_at, updated_at)
               VALUES (?, 'tagging', 'processing', datetime('now'), datetime('now'))""",
            (entry_id,),
        )
        dbw.commit()

    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()

        # Strip markdown code fence if present
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()

        matched_ids: list[int] = json.loads(raw)
        if not isinstance(matched_ids, list):
            raise ValueError(f"Expected list, got {type(matched_ids).__name__}: {raw!r}")

        valid_ids = {r["id"] for r in topic_rows}
        matched_ids = [int(tid) for tid in matched_ids if int(tid) in valid_ids]

        if matched_ids:
            with get_write_db() as dbw:
                for tid in matched_ids:
                    dbw.execute(
                        "INSERT OR IGNORE INTO library_entry_topics (entry_id, topic_id) VALUES (?, ?)",
                        (entry_id, tid),
                    )
                dbw.commit()

        with get_write_db() as dbw:
            dbw.execute(
                """UPDATE libby_enrichment_log
                   SET status = 'complete', updated_at = datetime('now')
                   WHERE entry_id = ? AND task = 'tagging'""",
                (entry_id,),
            )
            dbw.commit()

        logger.info(
            "Tagging complete for entry %d: %d topic(s) matched %s",
            entry_id, len(matched_ids), matched_ids,
        )

    except Exception as exc:
        logger.error("Tagging task failed for entry %d: %s", entry_id, exc)
        with get_write_db() as dbw:
            dbw.execute(
                """UPDATE libby_enrichment_log
                   SET status = 'failed', error = ?, updated_at = datetime('now')
                   WHERE entry_id = ? AND task = 'tagging'""",
                (str(exc)[:500], entry_id),
            )
            dbw.commit()

    # Always chain synopsis task (runs regardless of tagging outcome)
    _run_synopsis_task(entry_id)


# ---------------------------------------------------------------------------
# Vault home page helpers  (Items 4 & 5)
# ---------------------------------------------------------------------------

_VAULT_FOLDER_BY_TYPE: dict[str, str | None] = {
    "b": "Books",
    "a": "Articles", "e": "Articles", "r": "Articles",
    "p": "Media",    "v": "Media",    "m": "Media",
    "t": "Tools",    "w": "Tools",    "d": "Tools",
    "f": "Tools",    "c": "Tools",    "s": "Tools",  "z": "Tools",
    "n": None,       "q": None,
}


def _vault_entry_path(vault: Path, type_code: str, name: str) -> Path | None:
    """Return the expected Obsidian vault path for an entry, or None if no page."""
    folder = _VAULT_FOLDER_BY_TYPE.get(type_code)
    if folder is None:
        return None
    slug = _slugify(name)
    return vault / "Libby" / folder / f"{slug}.md"


# ---------------------------------------------------------------------------
# Background task: auto-synopsis via Claude API  (Item 4)
# ---------------------------------------------------------------------------

def _run_synopsis_task(entry_id: int) -> None:
    """Auto-generate a synopsis for a library entry using Claude.

    Chained after _run_tagging_task (called from the end of that function).
    Generates a 2–3 sentence synopsis, appends it to the entry's Obsidian
    vault home page (under a ## Synopsis heading), updates enrichment log,
    and sets needs_enrichment = 0 when done.
    """
    import json
    import anthropic
    from connectors.obsidian import get_vault_path

    db = get_db()

    # Load entry with author + assigned topics
    entry_row = db.execute(
        """
        SELECT e.id, e.name, e.type_code, e.url, e.comments,
               COALESCE(lb.author, li.author) AS author
        FROM library_entries e
        LEFT JOIN library_books lb ON e.type_code = 'b' AND e.entity_id = lb.id
        LEFT JOIN library_items li ON e.type_code != 'b' AND e.entity_id = li.id
        WHERE e.id = ?
        """,
        (entry_id,),
    ).fetchone()

    if not entry_row:
        logger.error("Synopsis task: entry %d not found", entry_id)
        return

    topic_rows = db.execute(
        """SELECT lt.code, lt.name
           FROM library_entry_topics jet
           JOIN library_topics lt ON jet.topic_id = lt.id
           WHERE jet.entry_id = ?""",
        (entry_id,),
    ).fetchall()

    type_name = _TYPE_NAMES.get(entry_row["type_code"], entry_row["type_code"])
    desc_lines = [
        f"Name: {entry_row['name']}",
        f"Type: {type_name}",
    ]
    if entry_row["author"]:
        desc_lines.append(f"Author: {entry_row['author']}")
    if entry_row["url"]:
        desc_lines.append(f"URL: {entry_row['url']}")
    if entry_row["comments"]:
        desc_lines.append(f"Notes: {entry_row['comments']}")
    if topic_rows:
        topic_str = ", ".join(f"{r['code']} ({r['name']})" for r in topic_rows)
        desc_lines.append(f"Topics: {topic_str}")
    resource_text = "\n".join(desc_lines)

    prompt = (
        "You are a personal librarian assistant. Write a concise 2–3 sentence synopsis "
        "for this resource that I can use as a quick reference.\n\n"
        f"{resource_text}\n\n"
        "Return ONLY the synopsis text. No heading, no markdown, no preamble."
    )

    # Mark as processing
    with get_write_db() as dbw:
        dbw.execute(
            """INSERT INTO libby_enrichment_log
               (entry_id, task, status, created_at, updated_at)
               VALUES (?, 'synopsis', 'processing', datetime('now'), datetime('now'))""",
            (entry_id,),
        )
        dbw.commit()

    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        synopsis = msg.content[0].text.strip()

        # Write synopsis to vault home page if it exists
        vault = get_vault_path()
        if vault:
            page_path = _vault_entry_path(vault, entry_row["type_code"], entry_row["name"])
            if page_path and page_path.exists():
                content = page_path.read_text(encoding="utf-8")
                if "## Synopsis" not in content:
                    content = content.rstrip() + f"\n\n## Synopsis\n\n{synopsis}\n"
                else:
                    # Replace existing synopsis section
                    content = re.sub(
                        r"(## Synopsis\s*\n)(.*?)(\n## |\Z)",
                        lambda m: m.group(1) + "\n" + synopsis + "\n" + m.group(3),
                        content,
                        flags=re.DOTALL,
                    )
                page_path.write_text(content, encoding="utf-8")
                logger.info("Synopsis written to %s", page_path)

        # Update log + clear needs_enrichment when both tasks complete
        with get_write_db() as dbw:
            dbw.execute(
                """UPDATE libby_enrichment_log
                   SET status = 'complete', updated_at = datetime('now')
                   WHERE entry_id = ? AND task = 'synopsis'""",
                (entry_id,),
            )
            # needs_enrichment → 0 when both tagging + synopsis are complete
            dbw.execute(
                """UPDATE library_entries SET needs_enrichment = 0, updated_at = datetime('now')
                   WHERE id = ?
                   AND (SELECT COUNT(*) FROM libby_enrichment_log
                        WHERE entry_id = ? AND status != 'complete') = 0""",
                (entry_id, entry_id),
            )
            dbw.commit()

        logger.info("Synopsis complete for entry %d", entry_id)

    except Exception as exc:
        logger.error("Synopsis task failed for entry %d: %s", entry_id, exc)
        with get_write_db() as dbw:
            dbw.execute(
                """UPDATE libby_enrichment_log
                   SET status = 'failed', error = ?, updated_at = datetime('now')
                   WHERE entry_id = ? AND task = 'synopsis'""",
                (str(exc)[:500], entry_id),
            )
            dbw.commit()


# ---------------------------------------------------------------------------
# Vault home page creation  (Item 5)
# ---------------------------------------------------------------------------

def _create_vault_home_page(
    entry_id: int,
    type_code: str,
    name: str,
    author: str | None = None,
    url: str | None = None,
    amazon_url: str | None = None,
    comments: str | None = None,
    priority: str = "medium",
    topic_codes: list[str] | None = None,
    isbn: str | None = None,
    publisher: str | None = None,
    year: int | str | None = None,
    status: str | None = None,
    subtitle: str | None = None,
    categories: list[str] | None = None,
    authors: list[str] | None = None,
) -> str | None:
    """Create an Obsidian vault note for a new library entry (synchronous).

    Writes a markdown file with YAML frontmatter under:
        <vault>/Libby/<Folder>/<slug>.md

    Folder mapping:
        b → Books/
        a, e, r → Articles/
        p, v, m → Media/
        t, w, d, f, c, s, z → Tools/
        n, q → (no page created)

    Returns the obsidian:// URI for the note, or None if no page is created.
    Sets library_entries.obsidian_link in the database.
    """
    from connectors.obsidian import get_vault_path, get_vault_name
    from urllib.parse import quote

    folder = _VAULT_FOLDER_BY_TYPE.get(type_code)
    if folder is None:
        return None  # n and q types get no vault page

    vault = get_vault_path()
    if not vault:
        logger.warning("Vault home page skipped for entry %d: vault not configured", entry_id)
        return None

    vault_name = get_vault_name()
    page_path = _vault_entry_path(vault, type_code, name)
    if page_path is None:
        return None

    # Don't overwrite if already exists
    if page_path.exists():
        logger.debug("Vault page already exists: %s", page_path)
        rel = page_path.relative_to(vault)
        link = f"obsidian://open?vault={quote(vault_name or '')}&file={quote(str(rel))}"
        return link

    # Build frontmatter
    type_name = _TYPE_NAMES.get(type_code, type_code)
    today = _date.today().isoformat()
    fm_lines = ["---"]
    fm_lines.append(f"type: {type_name.lower()}")
    fm_lines.append(f"priority: {priority}")
    if status:
        fm_lines.append(f"status: {status}")
    if author:
        fm_lines.append(f"author: \"{author}\"")
    if subtitle:
        fm_lines.append(f"subtitle: \"{subtitle}\"")
    if authors:
        fm_lines.append(f"authors: [{', '.join(repr(a) for a in authors)}]")
    if categories:
        fm_lines.append(f"categories: [{', '.join(repr(c) for c in categories)}]")
    if isbn:
        fm_lines.append(f"isbn: {isbn}")
    if publisher:
        fm_lines.append(f"publisher: \"{publisher}\"")
    if year:
        fm_lines.append(f"publish: {year}")
    if url:
        fm_lines.append(f"url: {url}")
    if amazon_url:
        fm_lines.append(f"amazon_url: {amazon_url}")
    if topic_codes:
        fm_lines.append(f"topics: [{', '.join(topic_codes)}]")
    fm_lines.append(f"created: {today}")
    fm_lines.append(f"updated: {today}")
    fm_lines.append("---")
    fm_lines.append("")
    fm_lines.append(f"# {name}")
    fm_lines.append("")
    if comments:
        fm_lines.append(f"> {comments}")
        fm_lines.append("")

    content = "\n".join(fm_lines)

    try:
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(content, encoding="utf-8")
        logger.info("Created vault home page: %s", page_path)
    except Exception as exc:
        logger.error("Failed to create vault page for entry %d: %s", entry_id, exc)
        return None

    # Build obsidian:// URI
    rel = page_path.relative_to(vault)
    link = f"obsidian://open?vault={quote(vault_name or '')}&file={quote(str(rel))}"

    # Persist obsidian_link
    try:
        with get_write_db() as dbw:
            dbw.execute(
                "UPDATE library_entries SET obsidian_link = ? WHERE id = ?",
                (link, entry_id),
            )
            dbw.commit()
    except Exception as exc:
        logger.error("Failed to persist obsidian_link for entry %d: %s", entry_id, exc)

    return link
