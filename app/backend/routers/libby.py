"""Libby — personal library management module.

Design: ~/Obsidian/MyNotes/Projects/Dashy/libby-design.md

Endpoints:
  GET  /api/libby/search                       — keyword + type + topic search
  GET  /api/libby/active-client                — default client for current session
  POST /api/libby/entries/{id}/action/copy     — return URL for clipboard
  POST /api/libby/entries/{id}/action/record   — log share, write Obsidian notes
  POST /api/libby/entries/{id}/action/make     — generate GitHub Pages HTML, git push, set webpage_url
"""

import html as _html
import logging
import re
import subprocess
from datetime import date as _date, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db, get_write_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/libby", tags=["libby"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}
_VALID_TYPE_CODES = frozenset("abptw")
_TYPE_NAMES = {
    "b": "book",
    "a": "article",
    "p": "podcast",
    "t": "tool",
    "w": "webpage",
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

    for token in q.strip().split():
        if re.fullmatch(r"[a-zA-Z]", token) and token.lower() in _VALID_TYPE_CODES:
            type_code = token.lower()
        elif token.startswith(".") and len(token) > 1:
            topic_prefixes.append(token[1:].lower())
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
def search_library(q: str = ""):
    """Search library entries using Libby query syntax.

    Returns up to 20 results ranked by: priority → name-match quality → frequency.
    """
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
            e.webpage_url,
            e.gdoc_id,
            CASE e.type_code
                WHEN 'b' THEN lb.author
                WHEN 'a' THEN la.author
                WHEN 'w' THEN lw.author
                WHEN 'p' THEN lp.host
                ELSE NULL
            END AS author
        FROM library_entries e
        LEFT JOIN library_books    lb ON e.type_code = 'b' AND e.entity_id = lb.id
        LEFT JOIN library_articles la ON e.type_code = 'a' AND e.entity_id = la.id
        LEFT JOIN library_webpages lw ON e.type_code = 'w' AND e.entity_id = lw.id
        LEFT JOIN library_podcasts lp ON e.type_code = 'p' AND e.entity_id = lp.id
        LEFT JOIN library_tools    lt ON e.type_code = 't' AND e.entity_id = lt.id
        WHERE 1=1
    """
    params: list = []

    if type_code:
        sql += " AND e.type_code = ?"
        params.append(type_code)

    for tok in name_tokens:
        sql += " AND lower(e.name) LIKE ?"
        params.append(f"%{tok}%")

    for pfx in topic_prefixes:
        sql += """
            AND e.id IN (
                SELECT jet.entry_id
                FROM library_entry_topics jet
                JOIN library_topics jt ON jet.topic_id = jt.id
                WHERE lower(jt.code) LIKE ?
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
            SELECT jet.entry_id, lt.code, lt.name
            FROM library_entry_topics jet
            JOIN library_topics lt ON jet.topic_id = lt.id
            WHERE jet.entry_id IN ({ph})
            """,
            entry_ids,
        ).fetchall():
            topics_by_entry.setdefault(tr["entry_id"], []).append(
                {"code": tr["code"], "name": tr["name"]}
            )

    # Score, rank, cap
    results = []
    for row in rows:
        name_score = _name_match_score(row["name"], name_tokens) if name_tokens else 1
        if name_tokens and name_score == 0:
            continue
        results.append({
            "id": row["id"],
            "name": row["name"],
            "type_code": row["type_code"],
            "priority": row["priority"],
            "frequency": row["frequency"],
            "url": row["url"],
            "amazon_url": row["amazon_url"],
            "webpage_url": row["webpage_url"],
            "gdoc_id": row["gdoc_id"],
            "author": row["author"],
            "topics": topics_by_entry.get(row["id"], []),
            "_rank": (
                _PRIORITY_RANK.get(row["priority"], 0),
                name_score,
                row["frequency"],
            ),
        })

    results.sort(key=lambda r: r["_rank"], reverse=True)
    for r in results:
        del r["_rank"]
    return results[:20]


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
# POST /api/libby/entries/{id}/action/copy
# ---------------------------------------------------------------------------

@router.post("/entries/{entry_id}/action/copy")
def action_copy(entry_id: int):
    """Return the canonical URL for an entry (for clipboard copy).

    Preference order: url → webpage_url → amazon_url.
    The frontend handles the actual clipboard write.
    """
    db = get_db()
    row = db.execute(
        "SELECT url, webpage_url, amazon_url FROM library_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"url": row["url"] or row["webpage_url"] or row["amazon_url"] or None}


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
    - library_entries.frequency += 1
    - **Resources Shared** bullet in today's Obsidian meeting note
    - ## Resources bullet on the client's Obsidian page
    - library_share_log row
    """
    from connectors.obsidian import get_vault_path

    db_r = get_db()

    # --- Validate entry ---
    entry_row = db_r.execute(
        "SELECT id, name, type_code, url, webpage_url FROM library_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if not entry_row:
        raise HTTPException(status_code=404, detail="Entry not found")

    # --- Validate client ---
    client_row = db_r.execute(
        "SELECT id, name, obsidian_name FROM billing_clients WHERE id = ?",
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

    logger.info(
        "Recorded entry %d (%s) for client %d (%s): %s",
        entry_id, entry_row["name"], body.client_id, client_row["name"], messages,
    )
    return {
        "status": "ok",
        "message": f"Recorded for {client_row['name']}",
        "details": messages,
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
            CASE e.type_code
                WHEN 'b' THEN lb.author
                WHEN 'a' THEN la.author
                WHEN 'w' THEN lw.author
                WHEN 'p' THEN lp.host
                ELSE NULL
            END AS author
        FROM library_entries e
        LEFT JOIN library_books    lb ON e.type_code = 'b' AND e.entity_id = lb.id
        LEFT JOIN library_articles la ON e.type_code = 'a' AND e.entity_id = la.id
        LEFT JOIN library_webpages lw ON e.type_code = 'w' AND e.entity_id = lw.id
        LEFT JOIN library_podcasts lp ON e.type_code = 'p' AND e.entity_id = lp.id
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
