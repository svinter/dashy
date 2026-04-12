"""Note creator connector — creates Obsidian daily and meeting notes for upcoming coaching sessions."""

import json
import logging
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path

# Emails to skip when matching attendees to clients (self + Google resource rooms)
_MY_EMAILS = frozenset(["steve.vinter@gmail.com", "svinter@gmail.com"])
_RESOURCE_RE = re.compile(r"@resource\.calendar\.google\.com$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Client title matching
# ---------------------------------------------------------------------------

_STRIP_SELF = re.compile(r'\bSteve(?:\s+Vinter)?\b', re.IGNORECASE)
_STRIP_NOISE = re.compile(
    r'\b(coaching|sync|bi.weekly|meeting|1:1|1on1|check.in|catch.up|weekly|monthly)\b',
    re.IGNORECASE,
)
_STRIP_SEP = re.compile(r'[/<>&|\\]+')


_COMPANY_LAST_WORDS = frozenset([
    'insights', 'tech', 'ai', 'lab', 'labs', 'inc', 'llc', 'corp', 'group',
    'services', 'solutions', 'team', 'health', 'agi', 'continua', 'labcentral',
    'artyfact', 'maven', 'layer', 'partners', 'ventures', 'studio', 'works',
])


def _looks_like_person(name: str) -> bool:
    """Return True if the name looks like 'Firstname Lastname' rather than a company/org name."""
    words = name.strip().split()
    if len(words) != 2:
        return False
    last = words[1].lower()
    return last not in _COMPANY_LAST_WORDS


def _build_client_lookups(clients: list[dict]) -> tuple[dict, dict]:
    """Return (by_full_name, by_first_name) dicts mapping lowercase → client row.

    by_first_name only includes entries where the first name is unique among
    person-looking clients (two-word names whose second word isn't a company noun).
    """
    by_full: dict[str, dict] = {}
    first_counts: dict[str, int] = {}
    by_first: dict[str, dict] = {}

    for c in clients:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        by_full[name.lower()] = c
        if _looks_like_person(name):
            first = name.split()[0].lower()
            first_counts[first] = first_counts.get(first, 0) + 1

    for c in clients:
        name = (c.get("name") or "").strip()
        if not name or not _looks_like_person(name):
            continue
        first = name.split()[0].lower()
        if first_counts[first] == 1:
            by_first[first] = c

    return by_full, by_first


def _match_client_by_title(title: str, by_full: dict, by_first: dict) -> dict | None:
    """Try to match a calendar event title to a billing_client row."""
    cleaned = _STRIP_SELF.sub('', title)
    cleaned = _STRIP_NOISE.sub('', cleaned)
    cleaned = _STRIP_SEP.sub(' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' -,·:')

    # Full name match on the cleaned string
    if cleaned.lower() in by_full:
        return by_full[cleaned.lower()]

    # Split into tokens and try each
    tokens = [t.strip(' -,.') for t in cleaned.split() if len(t.strip(' -,.')) > 1]
    matched = None
    for i, tok in enumerate(tokens):
        # Try "Firstname Lastname" (current + next token)
        if i + 1 < len(tokens):
            pair = f"{tok} {tokens[i + 1]}".lower()
            if pair in by_full:
                return by_full[pair]
        # Full name single token
        if tok.lower() in by_full:
            return by_full[tok.lower()]
        # Unique first name
        if tok.lower() in by_first:
            if matched is None:
                matched = by_first[tok.lower()]
            elif matched is not by_first[tok.lower()]:
                matched = None  # ambiguous — two different first-name matches
                break

    return matched

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------


def _parse_frontmatter_lines(content: str) -> tuple[list[str], int]:
    """Return (fm_lines, body_start_index) where fm_lines excludes the --- delimiters."""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return [], 0
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        i += 1
    return lines[1:i], i + 1


def _build_frontmatter(fields: list[tuple[str, str]]) -> str:
    """Build a YAML frontmatter block from ordered (key, value) pairs."""
    inner = "\n".join(f"{k}: {v}" for k, v in fields)
    return f"---\n{inner}\n---\n"


def _get_fm_value(fm_lines: list[str], key: str) -> str | None:
    for ln in fm_lines:
        m = re.match(rf"^{re.escape(key)}\s*:\s*(.*)", ln)
        if m:
            return m.group(1).strip().strip('"')
    return None


def _set_fm_value(fm_lines: list[str], key: str, value: str) -> tuple[list[str], bool]:
    """Return (updated_lines, changed)."""
    new_lines = []
    changed = False
    found = False
    for ln in fm_lines:
        m = re.match(rf"^{re.escape(key)}\s*:", ln)
        if m:
            new_line = f"{key}: {value}"
            if ln.strip() != new_line.strip():
                changed = True
            new_lines.append(new_line)
            found = True
        else:
            new_lines.append(ln)
    if not found:
        new_lines.append(f"{key}: {value}")
        changed = True
    return new_lines, changed


def _reassemble(fm_lines: list[str], body_lines: list[str]) -> str:
    return "---\n" + "\n".join(fm_lines) + "\n---\n" + "\n".join(body_lines)


# ---------------------------------------------------------------------------
# Daily note template
# ---------------------------------------------------------------------------

def _daily_note_content(note_date: date) -> str:
    prev_date = note_date - timedelta(days=1)
    next_date = note_date + timedelta(days=1)
    weekday = note_date.strftime("%A")
    date_str = note_date.isoformat()
    prev_str = prev_date.isoformat()
    next_str = next_date.isoformat()

    fm = _build_frontmatter([
        ("title", f'"{date_str}"'),
        ("type", "daily"),
        ("yesterday", f'"[[{prev_str}]]"'),
        ("day", weekday),
        ("tomorrow", f'"[[{next_str}]]"'),
        ("date", date_str),
    ])
    dataview_meetings = f"""\
```dataview
TABLE WITHOUT ID
    file.link as "Meeting",
    client as "Client",
    topic as "Topic"
FROM "8 Meetings"
WHERE date = date({date_str})
SORT meeting ASC
```"""
    body = f"""\
## Today's Meetings
{dataview_meetings}
---
## Notes
-
"""
    return fm + body


# ---------------------------------------------------------------------------
# Meeting note template
# ---------------------------------------------------------------------------

_DATAVIEW_HISTORY_TMPL = """\
```dataview
TABLE date AS "Date", topic AS "Topic", meeting AS "Meeting"
FROM "8 Meetings"
WHERE client = [[{client_obsidian_name}]] AND file.name != this.file.name
SORT date DESC
LIMIT 10
```"""


def _meeting_note_content(
    note_date: date,
    client_obsidian_name: str,
    duration_minutes: int,
    meeting_number: int,
    gdrive_url: str | None,
) -> str:
    date_str = note_date.isoformat()
    folder_val = gdrive_url or ""
    fm = _build_frontmatter([
        ("date", date_str),
        ("client", f'"[[{client_obsidian_name}]]"'),
        ("tags", ""),
        ("  - meeting", ""),
        ("  - coaching", ""),
        ("topic", "tbd"),
        ("transcript", "tbd"),
        ("type", "coaching"),
        ("duration", f'"{duration_minutes}"'),
        ("meeting", f'"{meeting_number}"'),
        ("folder", f'"{folder_val}"'),
    ])
    # Clean up the tags multi-line hack: use raw approach instead
    fm = (
        f"---\n"
        f"date: {date_str}\n"
        f"client: \"[[{client_obsidian_name}]]\"\n"
        f"tags:\n"
        f"  - meeting\n"
        f"  - coaching\n"
        f"topic: tbd\n"
        f"transcript: tbd\n"
        f"type: coaching\n"
        f"duration: \"{duration_minutes}\"\n"
        f"meeting: \"{meeting_number}\"\n"
        f"folder: \"{folder_val}\"\n"
        f"---\n"
    )
    dataview_history = _DATAVIEW_HISTORY_TMPL.format(client_obsidian_name=client_obsidian_name)
    body = f"""\
## History
{dataview_history}
---

## Granola Notes


## Notes
-

## Coaching Insights
-

## Action Items
-
"""
    return fm + body


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------


def create_upcoming_notes(days_ahead: int = 5, dry_run: bool = False) -> dict:
    """Create or update daily and meeting notes for upcoming coaching sessions.

    Set dry_run=True to compute what would happen without writing any files.

    Returns:
        dict with keys: daily_created, meeting_created, meeting_updated, skipped, log, dry_run
    """
    from connectors.obsidian import get_vault_path
    from database import get_db_connection

    vault = get_vault_path()
    if not vault:
        raise RuntimeError("Obsidian vault not configured")

    daily_dir = vault / "9 Daily"
    meetings_dir = vault / "8 Meetings"

    daily_dir.mkdir(exist_ok=True)
    meetings_dir.mkdir(exist_ok=True)

    today = date.today()
    end_date = today + timedelta(days=days_ahead)

    daily_created = 0
    meeting_created = 0
    meeting_updated = 0
    skipped = 0
    log: list[dict] = []

    # --- Create daily notes ---
    current = today
    while current <= end_date:
        fname = f"{current.isoformat()}.md"
        path = daily_dir / fname
        if not path.exists():
            if not dry_run:
                path.write_text(_daily_note_content(current), encoding="utf-8")
            daily_created += 1
            log.append({"status": "created", "type": "daily", "filename": fname})
            logger.info("%s daily note: %s", "Would create" if dry_run else "Created", path.name)
        current += timedelta(days=1)

    # --- Fetch upcoming grape/banana coaching sessions ---
    # Source of truth is calendar_events with color_id 3 (grape) or 5 (banana).
    # Most upcoming events have no billing_session yet — LEFT JOIN, don't filter on bs.
    with get_db_connection(readonly=True) as db:
        events = db.execute(
            """
            SELECT
                ce.id              AS ce_id,
                ce.start_time,
                ce.end_time,
                ce.summary         AS ce_summary,
                ce.attendees_json  AS ce_attendees,
                bs.client_id,
                bs.project_id,
                bc.obsidian_name   AS client_obsidian_name,
                bc.gdrive_coaching_docs_url AS client_gdrive_url,
                bp.obsidian_name   AS project_obsidian_name,
                bp.gdrive_coaching_docs_url AS project_gdrive_url
            FROM calendar_events ce
            LEFT JOIN billing_sessions bs ON bs.calendar_event_id = ce.id
            LEFT JOIN billing_clients bc ON bs.client_id = bc.id
            LEFT JOIN billing_projects bp ON bs.project_id = bp.id
            WHERE ce.color_id IN ('3', '5')
              AND date(ce.start_time) BETWEEN ? AND ?
            ORDER BY ce.start_time
            """,
            (today.isoformat(), end_date.isoformat()),
        ).fetchall()

        # Load all active clients for email-primary / title-fallback matching
        all_clients = db.execute(
            "SELECT id, name, obsidian_name, gdrive_coaching_docs_url, email FROM billing_clients WHERE active = 1"
        ).fetchall()

        # Get max confirmed session number per client
        client_max_rows = db.execute(
            """
            WITH sno AS (
                SELECT client_id,
                       ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY date) AS rn,
                       session_number
                FROM billing_sessions WHERE is_confirmed = 1
            )
            SELECT client_id, MAX(COALESCE(session_number, rn)) AS max_sn
            FROM sno GROUP BY client_id
            """
        ).fetchall()
        client_max_sessions: dict[int, int] = {r["client_id"]: r["max_sn"] for r in client_max_rows}

        project_max_rows = db.execute(
            """
            WITH sno AS (
                SELECT project_id,
                       ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY date) AS rn
                FROM billing_sessions WHERE is_confirmed = 1 AND project_id IS NOT NULL
            )
            SELECT project_id, MAX(rn) AS max_sn
            FROM sno GROUP BY project_id
            """
        ).fetchall()
        project_max_sessions: dict[int, int] = {r["project_id"]: r["max_sn"] for r in project_max_rows}

    by_full, by_first = _build_client_lookups([dict(c) for c in all_clients])
    by_email: dict[str, dict] = {
        c["email"].strip().lower(): dict(c)
        for c in all_clients
        if c["email"]
    }

    for row in events:
        try:
            start_dt = datetime.fromisoformat(row["start_time"])
            end_raw = row["end_time"]
            note_date = start_dt.date()

            # Compute duration, rounded up to nearest 30 min (e.g. 25→30, 55→60, 61→90)
            if end_raw:
                try:
                    end_dt = datetime.fromisoformat(end_raw)
                    raw_minutes = int((end_dt - start_dt).total_seconds() / 60)
                    duration_minutes = math.ceil(raw_minutes / 30) * 30
                except (ValueError, TypeError):
                    duration_minutes = 60
            else:
                duration_minutes = 60

            # Determine obsidian_name and meeting number.
            # Prefer billing_session link; fall back to title matching for unlinked events.
            if row["client_id"]:
                obs_name = row["client_obsidian_name"]
                gdrive_url = row["client_gdrive_url"]
                max_sn = client_max_sessions.get(row["client_id"], 0) or 0
            elif row["project_id"]:
                obs_name = row["project_obsidian_name"]
                gdrive_url = row["project_gdrive_url"]
                max_sn = project_max_sessions.get(row["project_id"], 0) or 0
            else:
                # No billing_session — try email match first, then title fallback
                matched = None
                if row["ce_attendees"]:
                    try:
                        attendees = json.loads(row["ce_attendees"])
                        for a in attendees:
                            email = (a.get("email") or "").strip().lower()
                            if not email:
                                continue
                            if email in _MY_EMAILS or _RESOURCE_RE.search(email):
                                continue
                            if email in by_email:
                                matched = by_email[email]
                                break
                    except Exception:
                        pass
                if not matched:
                    matched = _match_client_by_title(row["ce_summary"] or "", by_full, by_first)
                if not matched:
                    skipped += 1
                    logger.debug("No client match for calendar event: %s", row["ce_summary"])
                    continue
                obs_name = matched.get("obsidian_name") or matched.get("name")
                gdrive_url = matched.get("gdrive_coaching_docs_url")
                max_sn = client_max_sessions.get(matched["id"], 0) or 0

            if not obs_name:
                skipped += 1
                continue

            next_meeting_number = max_sn + 1
            fname = f"{note_date.isoformat()} - {obs_name}.md"
            note_path = meetings_dir / fname

            if not note_path.exists():
                # Create new note
                if not dry_run:
                    content = _meeting_note_content(
                        note_date, obs_name, duration_minutes, next_meeting_number, gdrive_url
                    )
                    note_path.write_text(content, encoding="utf-8")
                meeting_created += 1
                log.append({"status": "created", "type": "meeting", "filename": fname})
                logger.info("%s meeting note: %s", "Would create" if dry_run else "Created", fname)
            else:
                # Update frontmatter if changed (never touch topic/transcript if filled)
                content = note_path.read_text(encoding="utf-8")
                fm_lines, body_start = _parse_frontmatter_lines(content)
                body_lines = content.split("\n")[body_start:]
                changed = False

                # Update date
                fm_lines, c = _set_fm_value(fm_lines, "date", note_date.isoformat())
                changed = changed or c

                # Update duration
                fm_lines, c = _set_fm_value(fm_lines, "duration", f'"{duration_minutes}"')
                changed = changed or c

                # Update meeting number only
                existing_meeting = _get_fm_value(fm_lines, "meeting")
                if existing_meeting is None:
                    fm_lines, c = _set_fm_value(fm_lines, "meeting", f'"{next_meeting_number}"')
                    changed = changed or c

                if changed:
                    if not dry_run:
                        note_path.write_text(_reassemble(fm_lines, body_lines), encoding="utf-8")
                    meeting_updated += 1
                    log.append({"status": "updated", "type": "meeting", "filename": fname})
                    logger.info("%s meeting note frontmatter: %s", "Would update" if dry_run else "Updated", fname)
                else:
                    skipped += 1
                    log.append({"status": "skipped", "type": "meeting", "filename": fname})

        except Exception as e:
            logger.warning("Error processing session row: %s", e)
            skipped += 1

    return {
        "daily_created": daily_created,
        "meeting_created": meeting_created,
        "meeting_updated": meeting_updated,
        "skipped": skipped,
        "log": log,
        "dry_run": dry_run,
    }
