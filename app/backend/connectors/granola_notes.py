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
    """Fetch Granola notes created after `created_after`, with client-side date filtering.

    The API cursor-based pagination drops the created_after filter after page 1,
    so we apply the cutoff client-side and stop early once a full page is older
    than the cutoff (notes are returned newest-first).
    """
    headers = _api_headers()
    notes: list[dict] = []
    # Normalise cutoff to UTC-aware for comparison
    cutoff = created_after if created_after.tzinfo else created_after.replace(tzinfo=timezone.utc)
    params: dict = {"created_after": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")}
    logger.debug("Fetching Granola notes created_after=%s", params["created_after"])
    with httpx.Client(timeout=60) as client:
        while True:
            resp = client.get(f"{_BASE_URL}/notes", headers=headers, params=params)
            logger.debug("GET /notes → HTTP %d", resp.status_code)
            if resp.status_code != 200:
                logger.error("Granola API error %d: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("notes") or data.get("data") or []
            has_more = data.get("hasMore", True)
            cursor = data.get("next_cursor") or data.get("cursor")

            # Client-side filter: keep only notes at or after the cutoff.
            # Stop paginating early if all notes on this page are older (notes are newest-first).
            kept = []
            all_before_cutoff = bool(batch)  # assume true until we find one in range
            for n in batch:
                raw_ts = n.get("created_at") or ""
                try:
                    dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                    if dt >= cutoff:
                        kept.append(n)
                        all_before_cutoff = False
                except (ValueError, AttributeError):
                    kept.append(n)   # unparseable — keep to be safe
                    all_before_cutoff = False

            notes.extend(kept)
            logger.debug("Page: total=%d kept=%d has_more=%s", len(batch), len(kept), has_more)

            if not batch or not has_more or not cursor or all_before_cutoff:
                break
            params = {"cursor": cursor}

    logger.info("Fetched %d notes within cutoff (created_after=%s)", len(notes), cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"))
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


_GRANOLA_HEADING_RE = re.compile(
    r"^(#{1,6})[ \t]+granola[ \t]+notes[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)

_PLACEHOLDER_LINE_RE = re.compile(r"^\s*-\s*$")  # lines that are just "- " or "-"


def _find_granola_section(content: str) -> tuple[int, int, int, str] | None:
    """Locate the Granola Notes section, returning (heading_start, body_start, body_end, body).

    Matches any heading level (H1-H6) case-insensitively.
    The section ends at the next heading of equal or higher hierarchy (≤ level) or EOF.
    This means sub-headings inside the section (e.g. ### datestamp) are part of the body.
    """
    m = _GRANOLA_HEADING_RE.search(content)
    if not m:
        return None
    level = len(m.group(1))  # number of # chars in this heading
    body_start = m.end() + 1  # skip the newline that ends the heading line
    if body_start > len(content):
        body_start = len(content)
    # Stop at next heading with same or fewer # (same level or higher in hierarchy)
    stop_pat = re.compile(rf"^#{{1,{level}}}[ \t]", re.MULTILINE)
    stop_m = stop_pat.search(content, body_start)
    body_end = stop_m.start() if stop_m else len(content)
    body = content[body_start:body_end]
    return (m.start(), body_start, body_end, body)


def _granola_section_has_content(content: str) -> bool:
    """Return True if the Granola Notes section has real content.

    Ignores whitespace-only lines and template placeholder lines ("- " alone).
    A section with only "- " bullets (the Obsidian template default) is treated
    as empty so the sync will write into it.
    """
    result = _find_granola_section(content)
    if not result:
        return False
    _, _, _, body = result
    meaningful_lines = [
        ln for ln in body.splitlines()
        if ln.strip() and not _PLACEHOLDER_LINE_RE.match(ln)
    ]
    return bool(meaningful_lines)


def _count_granola_sections(content: str) -> int:
    """Count how many Granola Notes headings appear in the content (for duplicate detection)."""
    return len(_GRANOLA_HEADING_RE.findall(content))


def _update_granola_section(content: str, summary: str, sync_date: str, force: bool = False) -> str:
    """Write or append Granola summary into the Granola Notes section.

    If the section already has content and force=False, raises ValueError so the
    caller can skip the file.  With force=True, appends with a datestamp header.
    """
    result = _find_granola_section(content)
    if not result:
        # Section not found — append it
        new_section = f"\n## Granola Notes\n\n{summary.strip()}\n"
        return content + new_section

    heading_start, body_start, body_end, body = result
    # The heading line (including its newline) is content[heading_start:body_start]
    heading_line = content[heading_start:body_start]

    # Use same meaningful-content test as _granola_section_has_content
    meaningful = [
        ln for ln in body.splitlines()
        if ln.strip() and not _PLACEHOLDER_LINE_RE.match(ln)
    ]
    existing = "\n".join(meaningful)

    if not existing:
        new_block = f"{heading_line}\n{summary.strip()}\n\n"
    elif force:
        new_block = (
            f"{heading_line}\n{body.strip()}\n\n"
            f"---\n*Synced from Granola on {sync_date}*\n\n"
            f"{summary.strip()}\n\n"
        )
    else:
        raise ValueError("already_has_content")

    return content[:heading_start] + new_block + content[body_end:]


# ---------------------------------------------------------------------------
# Title → obsidian_name inference (fallback matching)
# ---------------------------------------------------------------------------

_MY_NAME_PATTERNS = [
    re.compile(r"\s+and\s+Steve(?:\s+Vinter)?", re.IGNORECASE),
    re.compile(r"Steve(?:\s+Vinter)?\s+and\s+", re.IGNORECASE),
    re.compile(r"\bwith\s+Steve(?:\s+Vinter)?\b", re.IGNORECASE),
    re.compile(r"^Steve(?:\s+Vinter)?[\s:,/]+", re.IGNORECASE),
    re.compile(r"[\s:,/]+Steve(?:\s+Vinter)?$", re.IGNORECASE),
]

_COMMON_SUFFIXES = re.compile(
    r"\s*[-–—/]\s*(1:1|1on1|check.in|coaching|session|meeting|catch.up|sync).*$",
    re.IGNORECASE,
)

_NOISE_WORDS = re.compile(
    r"\b(sync|check.in|session|meeting|coaching|weekly|bi.weekly|monthly|catch.up)\b",
    re.IGNORECASE,
)


def _infer_obsidian_name(title: str) -> str | None:
    """Strip the user's name and common noise from a Granola note title to get the client name.

    Handles slash-separated titles like 'Steve/Lauren' and 'Steve/Bob sync'.
    Returns the cleaned name, or None if it's too short to be useful.
    """
    name = title.strip()

    # Split on slash and drop any segment that is just "Steve [Vinter]"
    if "/" in name:
        parts = [p.strip() for p in name.split("/")]
        parts = [p for p in parts if not re.match(r"^Steve(?:\s+Vinter)?$", p, re.IGNORECASE)]
        name = " ".join(parts)

    for pat in _MY_NAME_PATTERNS:
        name = pat.sub("", name)
    name = _COMMON_SUFFIXES.sub("", name)
    name = _NOISE_WORDS.sub("", name)
    name = re.sub(r"\s{2,}", " ", name).strip(" -–—,:/·<>")
    return name if len(name) >= 2 else None


def _find_meeting_file(meetings_dir: Path, date_str: str, inferred_name: str) -> Path | None:
    """Find a meeting note by date + fuzzy name match.

    Tries exact match first, then scans all files for that date and scores
    by how many words from inferred_name appear in the filename stem.
    Also tries the day before (in case note was created just after midnight UTC
    but the meeting was local-time the previous day).
    """
    # Exact match
    exact = meetings_dir / f"{date_str} - {inferred_name}.md"
    if exact.exists():
        return exact

    name_lower = inferred_name.lower().strip()
    name_words = [w for w in name_lower.split() if len(w) > 2]

    # Try the note date and the day before (UTC vs local-time boundary)
    from datetime import date as _date, timedelta
    try:
        d = _date.fromisoformat(date_str)
        dates_to_try = [date_str, (d - timedelta(days=1)).isoformat()]
    except ValueError:
        dates_to_try = [date_str]

    for ds in dates_to_try:
        candidates = list(meetings_dir.glob(f"{ds} - *.md"))
        if not candidates:
            continue
        best_score, best_path = 0, None
        for p in candidates:
            fname_body = p.stem[len(ds) + 3:].lower()  # strip "YYYY-MM-DD - "
            if name_lower in fname_body:
                return p  # substring match wins immediately
            score = sum(1 for w in name_words if w in fname_body)
            if score > best_score:
                best_score, best_path = score, p
        if best_score > 0:
            logger.debug("Fuzzy match: %r → %s (score=%d)", inferred_name, best_path, best_score)
            return best_path

    return None


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


def sync_granola_notes(days_back: int = 7, force: bool = False, dry_run: bool = False) -> dict:
    """Sync Granola AI summaries into matching Obsidian session notes.

    By default, skips notes whose Granola Notes section already has content.
    Set force=True to append even when content exists (with a datestamp header).
    Set dry_run=True to fetch and match without writing any files.

    Returns:
        dict with keys: fetched, matched, written, skipped_existing, unmatched, errors, log, dry_run
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
    log: list[dict] = []

    for note in raw_notes:
        note_id = note.get("id") or note.get("note_id")
        title = note.get("title") or note.get("name") or ""
        logger.debug("Processing note: id=%s title=%r", note_id, title)
        note_url = _NOTE_URL_TEMPLATE.format(note_id=note_id)

        # Get event start time from the note (list endpoint has empty calendar_event;
        # detail endpoint has scheduled_start_time inside calendar_event)
        cal = note.get("calendar_event") or {}
        event_start_raw = (
            cal.get("scheduled_start_time")
            or cal.get("start_time")
            or note.get("event_start_time")
            or note.get("start_time")
        )
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
            # Fallback: infer from note title + created_at date, then fuzzy-scan files
            inferred = _infer_obsidian_name(title)
            created_raw = note.get("created_at") or note.get("date")
            logger.debug(
                "Fallback match: title=%r → inferred=%r created_at=%s",
                title, inferred, created_raw,
            )
            if inferred and created_raw:
                try:
                    note_date = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                    date_str = note_date.strftime("%Y-%m-%d")
                    obsidian_path = _find_meeting_file(meetings_dir, date_str, inferred)
                    if obsidian_path:
                        logger.debug("Fuzzy resolved %r → %s", title, obsidian_path.name)
                except (ValueError, AttributeError) as e:
                    logger.debug("Date parse failed for %r: %s", title, e)

            if not obsidian_path:
                unmatched.append(title)
                continue

        if not obsidian_path or not obsidian_path.exists():
            logger.debug("No matching Obsidian note for %r (path=%s)", title, obsidian_path)
            unmatched.append(title)
            log.append({"status": "unmatched", "title": title, "filename": None})
            continue

        fname = obsidian_path.name

        # --- Dry run: analyse file without fetching detail or writing ---
        if dry_run:
            try:
                content = _read_file(obsidian_path)
                has_content = _granola_section_has_content(content)
                dup_count = _count_granola_sections(content)
                if has_content and not force:
                    would_action = "skip"
                elif has_content and force:
                    would_action = "append"
                else:
                    would_action = "write"
                log.append({
                    "status": "dry_run",
                    "title": title,
                    "filename": fname,
                    "has_existing_granola_content": has_content,
                    "has_duplicate_granola_section": dup_count > 1,
                    "would_action": would_action,
                })
            except Exception as e:
                log.append({"status": "error", "title": title, "filename": fname, "error": str(e)})
            continue

        # --- Fetch note detail for summary ---
        try:
            detail = _fetch_note_detail(note_id)
        except Exception as e:
            logger.warning("Failed to fetch detail for note %r: %s", title, e)
            errors.append(f"{title}: fetch detail failed — {e}")
            log.append({"status": "error", "title": title, "filename": fname, "error": str(e)})
            continue

        summary = (
            detail.get("summary_markdown")
            or detail.get("summary_text")
            or detail.get("summary")
            or detail.get("ai_summary")
            or detail.get("content")
            or ""
        ).strip()
        if not summary:
            logger.debug("No summary in detail for %r; keys=%s", title, list(detail.keys()))
            unmatched.append(f"{title} (no summary)")
            log.append({"status": "unmatched", "title": title, "filename": fname, "error": "no summary"})
            continue

        # --- Write to Obsidian file ---
        try:
            content = _read_file(obsidian_path)
            try:
                content = _update_granola_section(content, summary, sync_date, force=force)
            except ValueError:
                # Section already has content and force=False — skip
                skipped_existing += 1
                logger.debug("Skipped %s — Granola Notes section already has content", fname)
                log.append({"status": "skipped", "title": title, "filename": fname})
                continue
            content = _set_frontmatter_field(content, "transcript", note_url)
            obsidian_path.write_text(content, encoding="utf-8")
            written += 1
            logger.info("Wrote Granola summary to %s", fname)
            log.append({"status": "synced", "title": title, "filename": fname})
        except Exception as e:
            logger.warning("Write failed for %s: %s", fname, e)
            errors.append(f"{fname}: write failed — {e}")
            log.append({"status": "error", "title": title, "filename": fname, "error": str(e)})

    logger.info(
        "Granola sync complete: fetched=%d matched=%d written=%d skipped=%d unmatched=%d errors=%d dry_run=%s",
        fetched, matched, written, skipped_existing, len(unmatched), len(errors), dry_run,
    )
    return {
        "fetched": fetched,
        "matched": matched,
        "written": written,
        "skipped_existing": skipped_existing,
        "unmatched": unmatched,
        "errors": errors,
        "log": log,
        "dry_run": dry_run,
    }
