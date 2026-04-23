"""Glance GCal import service.

Reads events from the configured "Glance" Google Calendar, parses each title
using the compact metadata syntax, creates glance_entries / glance_trips, then
deletes the source event.

Title format:  [<meta>] <label>
  meta = 0, 1, or 2 characters drawn from {s, p, k, o, y, t}
  name letters: s=steve, p=pgv, k=kpv, o=ovinters, y=york
  type letter:  t=travel  (absence = event)

Examples:
  "solo walk"      → steve event "solo walk"
  "s solo walk"    → steve event "solo walk"
  "st Azores"      → steve travel "Azores"
  "p recital"      → pgv event "recital"
  "pt Lisbon"      → pgv travel "Lisbon"
  "ot soccer camp" → ovinters travel "soccer camp"
  "kt Edinburgh"   → kpv travel "Edinburgh"
  "y HVAC service" → york event "HVAC service"
  "t dentist"      → steve travel "dentist"
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_META_CHARS = frozenset("spkoyt")
NAME_MAP = {
    "s": "steve",
    "p": "pgv",
    "k": "kpv",
    "o": "ovinters",
    "y": "york",
}
# lane mapping for event entries
MEMBER_LANE = {
    "steve":    "steve_events",
    "pgv":      "fam_events",
    "kpv":      "fam_events",
    "ovinters": "fam_events",
    "york":     "york",
}


# ---------------------------------------------------------------------------
# parse_glance_title — pure function
# ---------------------------------------------------------------------------

def parse_glance_title(title: str) -> dict:
    """Parse a Glance calendar event title into structured metadata.

    Returns:
        {
            'member': 'steve' | 'pgv' | 'kpv' | 'ovinters' | 'york',
            'is_travel': bool,
            'label': str,
            'valid': bool,
            'error': str | None,
        }
    """
    title = title.strip()
    if not title:
        return {"member": "steve", "is_travel": False, "label": "", "valid": False, "error": "empty title"}

    # Try to parse a 1- or 2-char metadata prefix
    # Rule: first 1 or 2 chars must ALL be in VALID_META_CHARS, next char must be a space
    meta = ""
    label = title

    for prefix_len in (2, 1):
        if len(title) > prefix_len and title[:prefix_len].lower() in _valid_prefixes(prefix_len) and title[prefix_len] == " ":
            meta = title[:prefix_len].lower()
            label = title[prefix_len:].lstrip()
            break

    # Parse meta into name + type
    name_letter = None
    is_travel = False
    for ch in meta:
        if ch == "t":
            is_travel = True
        elif ch in NAME_MAP:
            name_letter = ch

    member = NAME_MAP.get(name_letter, "steve")

    # Edge case: york + travel is invalid — treat as york event, log warning
    if member == "york" and is_travel:
        logger.warning(
            "parse_glance_title: 'y' (york) combined with 't' (travel) is invalid — "
            "treating as york event. Title: %r", title
        )
        is_travel = False

    return {
        "member": member,
        "is_travel": is_travel,
        "label": label,
        "valid": True,
        "error": None,
    }


def _valid_prefixes(n: int) -> frozenset[str]:
    """All n-char strings where every character is in VALID_META_CHARS."""
    if n == 1:
        return frozenset(VALID_META_CHARS)
    # 2-char: both chars valid
    return frozenset(
        a + b
        for a in VALID_META_CHARS
        for b in VALID_META_CHARS
    )


# ---------------------------------------------------------------------------
# GCal helpers
# ---------------------------------------------------------------------------

def _get_calendar_service():
    from connectors.google_auth import get_google_credentials
    from googleapiclient.discovery import build
    creds = get_google_credentials()
    return build("calendar", "v3", credentials=creds)


def _get_calendar_id() -> str | None:
    try:
        from app_config import get_dashy_config
        cfg = get_dashy_config()
        cal_id = cfg.get("glance", {}).get("gcal_calendar_id", "").strip()
        return cal_id or None
    except Exception:
        return None


def _event_dates(event: dict) -> tuple[date, date]:
    """Return (start_date, end_date) for a GCal event (all-day or timed)."""
    start_raw = event.get("start", {})
    end_raw = event.get("end", {})

    start_str = start_raw.get("date") or start_raw.get("dateTime", "")[:10]
    end_str   = end_raw.get("date")   or end_raw.get("dateTime", "")[:10]

    start = date.fromisoformat(start_str)
    end_gcal = date.fromisoformat(end_str)

    # GCal all-day events use exclusive end date (end = day after last)
    if "date" in start_raw:
        end_gcal = end_gcal - timedelta(days=1)

    return start, max(start, end_gcal)


def _date_range(start: date, end: date) -> list[date]:
    days: list[date] = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days


def _compute_default_marks(start: date, end: date) -> list[dict]:
    """Mirror of routers/glance.py _compute_default_marks."""
    days = _date_range(start, end)
    n = len(days)
    result = []
    for i, d in enumerate(days):
        if n == 1:
            result.append({"date": d.isoformat(), "depart": True, "sleep": False, "return": True})
        elif i == 0:
            result.append({"date": d.isoformat(), "depart": True, "sleep": True, "return": False})
        elif i == n - 1:
            result.append({"date": d.isoformat(), "depart": False, "sleep": False, "return": True})
        else:
            result.append({"date": d.isoformat(), "depart": False, "sleep": True, "return": False})
    return result


def _resolve_or_create_location(db, location_name: str) -> str:
    """Mirror of routers/glance.py _resolve_or_create_location for a name-only input."""
    name = location_name.strip()
    row = db.execute(
        "SELECT id FROM glance_locations WHERE LOWER(display) = LOWER(?)", (name,)
    ).fetchone()
    if row:
        return row["id"]
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    row = db.execute("SELECT id FROM glance_locations WHERE id = ?", (slug,)).fetchone()
    if row:
        return slug
    db.execute(
        "INSERT INTO glance_locations (id, display, color_bg, color_text, is_home, is_york) "
        "VALUES (?, ?, '#EF997A', '#4A1B0C', 0, 0)",
        (slug, name),
    )
    return slug


# ---------------------------------------------------------------------------
# process_glance_calendar — main import function
# ---------------------------------------------------------------------------

def process_glance_calendar(db) -> dict:
    """Fetch all events from the Glance GCal calendar and import them.

    Args:
        db: open read/write database connection (sqlite3 row_factory set)

    Returns:
        { 'imported': int, 'skipped': int, 'errors': list, 'items': list }
    """
    cal_id = _get_calendar_id()
    if not cal_id:
        return {
            "imported": 0,
            "skipped": 0,
            "errors": ["glance.gcal_calendar_id not configured in dashy_config.json"],
            "items": [],
        }

    try:
        service = _get_calendar_service()
    except Exception as exc:
        logger.error("GCal auth failed for Glance import: %s", exc)
        return {"imported": 0, "skipped": 0, "errors": [f"GCal auth failed: {exc}"], "items": []}

    # Fetch all events (paginate)
    events: list[dict] = []
    page_token = None
    try:
        while True:
            kwargs: dict[str, Any] = {
                "calendarId": cal_id,
                "singleEvents": True,
                "orderBy": "startTime",
                "maxResults": 250,
            }
            if page_token:
                kwargs["pageToken"] = page_token
            result = service.events().list(**kwargs).execute()
            events.extend(result.get("items", []))
            page_token = result.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        logger.error("GCal fetch failed for Glance import: %s", exc)
        return {"imported": 0, "skipped": 0, "errors": [f"GCal fetch failed: {exc}"], "items": []}

    imported = 0
    skipped = 0
    errors: list[str] = []
    items: list[dict] = []

    for event in events:
        event_id = event.get("id", "")
        raw_title = (event.get("summary") or "").strip()

        # Check idempotency: if already imported AND deleted, skip
        existing = db.execute(
            "SELECT id, target_type, target_id, deleted_from_gcal FROM glance_gcal_imports WHERE gcal_event_id = ?",
            (event_id,),
        ).fetchone()
        if existing and existing["deleted_from_gcal"] == 1:
            skipped += 1
            continue

        # Parse title
        parsed = parse_glance_title(raw_title)
        if not parsed["valid"]:
            errors.append(f"⚠ could not parse: {raw_title!r} (event id: {event_id})")
            skipped += 1
            continue

        member  = parsed["member"]
        is_travel = parsed["is_travel"]
        label   = parsed["label"]

        try:
            start_date, end_date = _event_dates(event)
        except Exception as exc:
            errors.append(f"⚠ bad dates on: {raw_title!r}: {exc}")
            skipped += 1
            continue

        # If re-importing: delete previous target
        if existing:
            _delete_previous_target(db, existing["target_type"], existing["target_id"])

        parse_result_json = json.dumps(parsed)

        if is_travel:
            target_id, item_desc = _import_trip(db, member, label, start_date, end_date, event_id)
            target_type = "trip"
        else:
            target_id, item_desc = _import_entries(db, member, label, start_date, end_date, event_id)
            target_type = "entry"

        # Upsert import record
        db.execute(
            """
            INSERT INTO glance_gcal_imports
                (gcal_event_id, target_type, target_id, parse_result, deleted_from_gcal)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(gcal_event_id) DO UPDATE SET
                target_type        = excluded.target_type,
                target_id          = excluded.target_id,
                parse_result       = excluded.parse_result,
                deleted_from_gcal  = 0,
                imported_at        = CURRENT_TIMESTAMP
            """,
            (event_id, target_type, target_id, parse_result_json),
        )

        # Delete from GCal
        gcal_deleted = False
        try:
            service.events().delete(calendarId=cal_id, eventId=event_id).execute()
            gcal_deleted = True
        except Exception as exc:
            logger.warning("Could not delete GCal event %s: %s", event_id, exc)
            errors.append(f"⚠ imported but GCal delete failed for: {raw_title!r}")

        if gcal_deleted:
            db.execute(
                "UPDATE glance_gcal_imports SET deleted_from_gcal = 1 WHERE gcal_event_id = ?",
                (event_id,),
            )

        db.commit()
        imported += 1
        items.append(item_desc)

    return {"imported": imported, "skipped": skipped, "errors": errors, "items": items}


def _delete_previous_target(db, target_type: str, target_id: int) -> None:
    """Delete the previously created entry or trip (cascade handles trip_days)."""
    try:
        if target_type == "trip":
            db.execute("DELETE FROM glance_trips WHERE id = ?", (target_id,))
        elif target_type == "entry":
            db.execute("DELETE FROM glance_entries WHERE id = ?", (target_id,))
    except Exception as exc:
        logger.warning("Could not delete previous target %s/%s: %s", target_type, target_id, exc)


def _import_trip(db, member: str, label: str, start_date: date, end_date: date, gcal_event_id: str) -> tuple[int, dict]:
    """Create a glance_trip with default day marks. Returns (trip_id, item_desc)."""
    location_id = _resolve_or_create_location(db, label)
    marks = _compute_default_marks(start_date, end_date)

    cur = db.execute(
        "INSERT INTO glance_trips (member_id, location_id, start_date, end_date, source, source_ref) "
        "VALUES (?, ?, ?, ?, 'gcal_glance_import', ?)",
        (member, location_id, start_date.isoformat(), end_date.isoformat(), gcal_event_id),
    )
    trip_id = cur.lastrowid

    for m in marks:
        db.execute(
            'INSERT INTO glance_trip_days (trip_id, date, depart, sleep, "return") '
            "VALUES (?, ?, ?, ?, ?)",
            (trip_id, m["date"], m["depart"], m["sleep"], m["return"]),
        )

    date_range = start_date.isoformat() if start_date == end_date else f"{start_date}–{end_date}"
    return trip_id, {
        "gcal_title": label,
        "parsed_label": label,
        "member": member,
        "type": "travel",
        "lane": "steve_travel" if member == "steve" else "fam_travel",
        "date_range": date_range,
    }


def _import_entries(db, member: str, label: str, start_date: date, end_date: date, gcal_event_id: str) -> tuple[int, dict]:
    """Create one glance_entry per day in the date range. Returns (first_entry_id, item_desc)."""
    lane = MEMBER_LANE.get(member, "steve_events")
    member_id = member if member != "steve" else None
    # For steve lane, no member_id needed (lane is sufficient)
    # For york lane, no member_id either
    if member in ("steve", "york"):
        member_id = None

    days = _date_range(start_date, end_date)
    first_id = None
    for d in days:
        cur = db.execute(
            "INSERT INTO glance_entries (lane, member_id, date, label, source, source_ref) "
            "VALUES (?, ?, ?, ?, 'gcal_glance_import', ?)",
            (lane, member_id, d.isoformat(), label, gcal_event_id),
        )
        if first_id is None:
            first_id = cur.lastrowid

    date_range = start_date.isoformat() if start_date == end_date else f"{start_date}–{end_date}"
    return first_id, {
        "gcal_title": label,
        "parsed_label": label,
        "member": member,
        "type": "event",
        "lane": lane,
        "date_range": date_range,
    }
