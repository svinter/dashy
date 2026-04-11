"""Granola Notes connector — syncs Granola AI summaries into Obsidian session notes.

Uses the Granola public REST API (https://public-api.granola.ai/v1/).
Distinct from connectors/granola.py which reads the local MCP cache.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://public-api.granola.ai/v1"
_NOTE_URL_TEMPLATE = "https://notes.granola.ai/t/{note_id}"

# ---------------------------------------------------------------------------
# Granola API helpers
# ---------------------------------------------------------------------------


def _api_headers() -> dict:
    from app_config import get_secret

    key = get_secret("GRANOLA_API_KEY")
    if not key:
        raise RuntimeError("GRANOLA_API_KEY not configured — add it in Settings → Connectors")
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def _fetch_notes(created_after: datetime) -> list[dict]:
    """Fetch all Granola notes created after `created_after` (handles pagination)."""
    headers = _api_headers()
    notes: list[dict] = []
    params: dict = {"created_after": created_after.isoformat()}
    with httpx.Client(timeout=30) as client:
        while True:
            resp = client.get(f"{_BASE_URL}/notes", headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("notes") or data.get("data") or []
            notes.extend(batch)
            cursor = data.get("next_cursor") or data.get("cursor")
            if not cursor or not batch:
                break
            params = {"cursor": cursor}
    return notes


def _fetch_note_detail(note_id: str) -> dict:
    """Fetch a single Granola note with transcript included."""
    headers = _api_headers()
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{_BASE_URL}/notes/{note_id}",
            headers=headers,
            params={"include": "transcript"},
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Obsidian file helpers
# ---------------------------------------------------------------------------


def _read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_without_frontmatter).

    Frontmatter is raw lines between first --- and second ---; returned as
    dict of key → raw value string.  Body is everything after the closing ---.
    """
    lines = content.split("\n")
    fm: dict[str, str] = {}
    body_start = 0

    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            m = re.match(r"^(\w[\w\-]*):\s*(.*)", lines[i])
            if m:
                fm[m.group(1)] = m.group(2).strip()
            i += 1
        body_start = i + 1  # skip closing ---

    body = "\n".join(lines[body_start:])
    return fm, body


def _set_frontmatter_field(content: str, key: str, value: str) -> str:
    """Set or overwrite a single frontmatter key in the file content string."""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        # No frontmatter — prepend one
        fm_block = f"---\n{key}: {value}\n---\n"
        return fm_block + content

    # Find closing ---
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        i += 1

    fm_lines = lines[1:i]
    # Remove existing key if present
    fm_lines = [ln for ln in fm_lines if not re.match(rf"^{re.escape(key)}\s*:", ln)]
    # Append new value
    fm_lines.append(f"{key}: {value}")

    result = ["---"] + fm_lines + ["---"] + lines[i + 1 :]
    return "\n".join(result)


_GRANOLA_SECTION_RE = re.compile(r"(## Granola Notes\s*\n)(.*?)(?=\n## |\Z)", re.DOTALL)


def _granola_section_has_content(content: str) -> bool:
    """Return True if the ## Granola Notes section already has non-whitespace content."""
    m = _GRANOLA_SECTION_RE.search(content)
    if not m:
        return False
    return bool(m.group(2).strip())


def _update_granola_section(content: str, summary: str, sync_date: str, force: bool = False) -> str:
    """Write or append Granola summary into the '## Granola Notes' section.

    If the section already has content and force=False, raises ValueError so the
    caller can skip the file.  With force=True, appends with a datestamp header.
    """
    m = _GRANOLA_SECTION_RE.search(content)
    if not m:
        # Section not found — append it
        new_section = f"\n## Granola Notes\n\n{summary.strip()}\n"
        return content + new_section

    header = m.group(1)  # "## Granola Notes\n"
    existing = m.group(2).strip()
    start, end = m.start(), m.end()

    if not existing:
        new_block = f"{header}\n{summary.strip()}\n\n"
    elif force:
        new_block = (
            f"{header}\n{existing}\n\n"
            f"---\n*Synced from Granola on {sync_date}*\n\n"
            f"{summary.strip()}\n\n"
        )
    else:
        raise ValueError("already_has_content")

    return content[:start] + new_block + content[end:]


# ---------------------------------------------------------------------------
# Title → obsidian_name inference (fallback matching)
# ---------------------------------------------------------------------------

_MY_NAME_PATTERNS = [
    re.compile(r"\s+and\s+Steve(?:\s+Vinter)?", re.IGNORECASE),
    re.compile(r"Steve(?:\s+Vinter)?\s+and\s+", re.IGNORECASE),
    re.compile(r"\bwith\s+Steve(?:\s+Vinter)?\b", re.IGNORECASE),
    re.compile(r"^Steve(?:\s+Vinter)?[\s:,]+", re.IGNORECASE),
    re.compile(r"[\s:,]+Steve(?:\s+Vinter)?$", re.IGNORECASE),
]

_COMMON_SUFFIXES = re.compile(
    r"\s*[-–—]\s*(1:1|1on1|check.in|coaching|session|meeting|catch.up).*$",
    re.IGNORECASE,
)


def _infer_obsidian_name(title: str) -> str | None:
    """Strip the user's name and common suffixes from a Granola note title to get the client name."""
    name = title.strip()
    for pat in _MY_NAME_PATTERNS:
        name = pat.sub("", name)
    name = _COMMON_SUFFIXES.sub("", name)
    name = name.strip(" -–—,:")
    return name if len(name) >= 2 else None


# ---------------------------------------------------------------------------
# Calendar event time parsing
# ---------------------------------------------------------------------------


def _parse_event_time(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Main sync function
# ---------------------------------------------------------------------------


def sync_granola_notes(days_back: int = 30, force: bool = False) -> dict:
    """Sync Granola AI summaries into matching Obsidian session notes.

    By default, skips notes whose ## Granola Notes section already has content.
    Set force=True to append even when content exists (with a datestamp header).

    Returns:
        dict with keys: fetched, matched, written, skipped_existing, unmatched, errors
    """
    from connectors.obsidian import get_vault_path
    from database import get_db_connection

    vault = get_vault_path()
    if not vault:
        raise RuntimeError("Obsidian vault not configured")

    meetings_dir = vault / "8 Meetings"
    if not meetings_dir.is_dir():
        raise RuntimeError(f"Obsidian meetings dir not found: {meetings_dir}")

    created_after = datetime.now(tz=timezone.utc) - timedelta(days=days_back)
    sync_date = datetime.now().strftime("%Y-%m-%d")

    # --- Load billing sessions with calendar event times ---
    with get_db_connection(readonly=True) as db:
        session_rows = db.execute(
            """
            SELECT
                bs.id,
                bs.obsidian_note_path,
                bs.date,
                ce.start_time AS event_start,
                bc.obsidian_name AS client_obsidian_name,
                bp.obsidian_name AS project_obsidian_name
            FROM billing_sessions bs
            LEFT JOIN calendar_events ce ON bs.calendar_event_id = ce.id
            LEFT JOIN billing_clients bc ON bs.client_id = bc.id
            LEFT JOIN billing_projects bp ON bs.project_id = bp.id
            WHERE bs.is_confirmed = 1
              AND bs.date >= ?
            """,
            ((datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d"),),
        ).fetchall()

    # Build index: event start time (rounded to minute) → session info
    # Store as list to handle rare duplicates
    EventKey = tuple  # (year, month, day, hour, minute)

    def _time_key(ts: str | None) -> EventKey | None:
        dt = _parse_event_time(ts)
        if not dt:
            return None
        return (dt.year, dt.month, dt.day, dt.hour, dt.minute)

    sessions_by_time: dict[EventKey, dict] = {}
    for row in session_rows:
        key = _time_key(row["event_start"])
        if key:
            sessions_by_time[key] = dict(row)

    # Fetch Granola notes
    logger.info("Fetching Granola notes created after %s", created_after.isoformat())
    raw_notes = _fetch_notes(created_after)
    logger.info("Fetched %d Granola notes", len(raw_notes))

    fetched = len(raw_notes)
    matched = 0
    written = 0
    skipped_existing = 0
    unmatched: list[str] = []
    errors: list[str] = []

    for note in raw_notes:
        note_id = note.get("id") or note.get("note_id")
        title = note.get("title") or note.get("name") or ""
        note_url = _NOTE_URL_TEMPLATE.format(note_id=note_id)

        # Get event start time from the note
        event_start_raw = (
            note.get("calendar_event", {}) or {}
        ).get("start_time") or note.get("event_start_time") or note.get("start_time")
        note_key = _time_key(event_start_raw)

        # --- Find matching session ---
        session = None
        obsidian_path: Path | None = None

        if note_key:
            # Try ±15 min window
            for minute_offset in range(-15, 16):
                offset_dt = datetime(
                    note_key[0], note_key[1], note_key[2],
                    note_key[3], note_key[4], tzinfo=timezone.utc
                ) + timedelta(minutes=minute_offset)
                candidate_key = (
                    offset_dt.year, offset_dt.month, offset_dt.day,
                    offset_dt.hour, offset_dt.minute,
                )
                if candidate_key in sessions_by_time:
                    session = sessions_by_time[candidate_key]
                    break

        if session and session.get("obsidian_note_path"):
            rel = session["obsidian_note_path"]
            obsidian_path = vault / rel
            matched += 1

        elif session:
            # Session matched but no obsidian_note_path — infer from date+client name
            obs_name = session.get("client_obsidian_name") or session.get("project_obsidian_name")
            if obs_name and session.get("date"):
                obsidian_path = meetings_dir / f"{session['date']} - {obs_name}.md"
            matched += 1

        else:
            # Fallback: infer from note title+date
            inferred = _infer_obsidian_name(title)
            created_raw = note.get("created_at") or note.get("date")
            if inferred and created_raw:
                try:
                    note_date = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                    date_str = note_date.strftime("%Y-%m-%d")
                    obsidian_path = meetings_dir / f"{date_str} - {inferred}.md"
                except (ValueError, AttributeError):
                    pass

            if not obsidian_path:
                unmatched.append(title)
                continue

        if not obsidian_path or not obsidian_path.exists():
            unmatched.append(title)
            continue

        # --- Fetch note detail for summary ---
        try:
            detail = _fetch_note_detail(note_id)
        except Exception as e:
            errors.append(f"{title}: fetch detail failed — {e}")
            continue

        summary = (
            detail.get("summary")
            or detail.get("ai_summary")
            or detail.get("content")
            or ""
        ).strip()
        if not summary:
            unmatched.append(f"{title} (no summary)")
            continue

        # --- Write to Obsidian file ---
        try:
            content = _read_file(obsidian_path)
            try:
                content = _update_granola_section(content, summary, sync_date, force=force)
            except ValueError:
                # Section already has content and force=False — skip
                skipped_existing += 1
                logger.debug("Skipped %s — Granola Notes section already has content", obsidian_path.name)
                continue
            content = _set_frontmatter_field(content, "transcript", note_url)
            obsidian_path.write_text(content, encoding="utf-8")
            written += 1
            logger.info("Wrote Granola summary to %s", obsidian_path.name)
        except Exception as e:
            errors.append(f"{obsidian_path.name}: write failed — {e}")

    return {
        "fetched": fetched,
        "matched": matched,
        "written": written,
        "skipped_existing": skipped_existing,
        "unmatched": unmatched,
        "errors": errors,
    }
