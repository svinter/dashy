"""Google Calendar API connector."""

import json
import logging
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from app_config import load_config
from config import CALENDAR_DAYS_AHEAD, CALENDAR_DAYS_BEHIND
from connectors.google_auth import get_google_credentials
from database import batch_upsert, get_write_db

logger = logging.getLogger(__name__)


def _duration_hours(start_raw: str, end_raw: str) -> float | None:
    """Return duration in hours between two ISO datetime strings, or None on error."""
    try:
        s = datetime.fromisoformat(start_raw)
        e = datetime.fromisoformat(end_raw)
        delta = (e - s).total_seconds() / 3600
        return round(delta, 4) if delta > 0 else None
    except (ValueError, TypeError):
        return None


def sync_calendar_events() -> int:
    creds = get_google_credentials()
    service = build("calendar", "v3", credentials=creds)

    # Get user email for self-response detection (fallback when API self flag is missing)
    cfg = load_config()
    user_email = cfg.get("profile", {}).get("user_email", "").lower()

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=CALENDAR_DAYS_BEHIND)).isoformat()
    time_max = (now + timedelta(days=CALENDAR_DAYS_AHEAD)).isoformat()

    # Phase 1: Fetch all events from API (no DB connection held)
    events = []
    page_token = None
    while True:
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=2500,
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
            )
            .execute()
        )
        events.extend(events_result.get("items", []))
        page_token = events_result.get("nextPageToken")
        if not page_token:
            break

    # Phase 2: Build rows (skip cancelled events)
    rows = []
    for event in events:
        status = event.get("status", "confirmed")
        if status == "cancelled":
            continue

        start = event.get("start", {})
        end = event.get("end", {})
        start_time = start.get("dateTime", start.get("date", ""))
        end_time = end.get("dateTime", end.get("date", ""))
        all_day = "date" in start and "dateTime" not in start

        # Track the current user's RSVP response
        self_response = ""
        attendees = []
        for a in event.get("attendees", []):
            attendees.append(
                {
                    "email": a.get("email", ""),
                    "name": a.get("displayName", ""),
                    "response": a.get("responseStatus", ""),
                }
            )
            # Use API self flag, or match by user email from profile
            if a.get("self") or (user_email and a.get("email", "").lower() == user_email):
                self_response = a.get("responseStatus", "")

        # Skip events the user has declined
        if self_response == "declined":
            continue

        rows.append(
            (
                event["id"],
                event.get("summary", "(No title)"),
                event.get("description", ""),
                event.get("location", ""),
                start_time,
                end_time,
                int(all_day),
                json.dumps(attendees),
                event.get("organizer", {}).get("email", ""),
                "primary",
                event.get("htmlLink", ""),
                status,
                self_response,
                event.get("colorId", ""),
            )
        )

    # Phase 3: Write in batches and remove deleted events
    fetched_ids = {row[0] for row in rows}
    # Build a map of incoming event id → (start_time, end_time) for duration comparison
    incoming_duration: dict[str, tuple[str, str]] = {
        row[0]: (row[4], row[5]) for row in rows  # (id, ..., start_time, end_time, ...)
    }

    with get_write_db() as db:
        # Snapshot existing durations for events that have confirmed billing sessions,
        # BEFORE the upsert replaces them.
        billed_event_ids = [
            r[0] for r in db.execute(
                """SELECT DISTINCT ce.id FROM calendar_events ce
                   JOIN billing_sessions bs ON bs.calendar_event_id = ce.id
                   WHERE bs.is_confirmed = 1 AND bs.dismissed = 0
                     AND bs.invoice_line_id IS NULL
                     AND ce.id IN (%s)"""
                % ",".join("?" * len(fetched_ids)),
                list(fetched_ids),
            ).fetchall()
        ] if fetched_ids else []

        old_times: dict[str, tuple[str, str]] = {}
        if billed_event_ids:
            placeholders = ",".join("?" * len(billed_event_ids))
            for r in db.execute(
                f"SELECT id, start_time, end_time FROM calendar_events WHERE id IN ({placeholders})",
                billed_event_ids,
            ).fetchall():
                old_times[r["id"]] = (r["start_time"], r["end_time"])

        batch_upsert(
            db,
            """INSERT OR REPLACE INTO calendar_events
               (id, summary, description, location, start_time, end_time, all_day,
                attendees_json, organizer_email, calendar_id, html_link,
                status, self_response, color_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

        # Propagate duration changes to billing_sessions
        for ev_id, (old_start, old_end) in old_times.items():
            new_start, new_end = incoming_duration.get(ev_id, (old_start, old_end))
            old_h = _duration_hours(old_start, old_end)
            new_h = _duration_hours(new_start, new_end)
            if old_h is None or new_h is None or abs(old_h - new_h) < 0.001:
                continue

            # Update all confirmed, non-invoiced sessions linked to this event
            sessions = db.execute(
                """SELECT bs.id, bs.client_id, bs.rate, bc.name AS client_name, bs.date
                   FROM billing_sessions bs
                   LEFT JOIN billing_clients bc ON bc.id = bs.client_id
                   WHERE bs.calendar_event_id = ? AND bs.is_confirmed = 1
                     AND bs.dismissed = 0 AND bs.invoice_line_id IS NULL""",
                (ev_id,),
            ).fetchall()

            for sess in sessions:
                new_amount = round(new_h * sess["rate"], 2) if sess["rate"] else None
                db.execute(
                    "UPDATE billing_sessions SET duration_hours = ?, amount = ? WHERE id = ?",
                    (new_h, new_amount, sess["id"]),
                )
                logger.info(
                    "Updated session duration: %s %s %.4fh → %.4fh (amount: %s)",
                    sess["client_name"] or f"session-{sess['id']}",
                    sess["date"],
                    old_h,
                    new_h,
                    new_amount,
                )

        # Remove events that exist in the DB within the sync window but were
        # not returned by the API (i.e. deleted/cancelled in Google Calendar)
        if fetched_ids:
            placeholders = ",".join("?" * len(fetched_ids))
            db.execute(
                f"""DELETE FROM calendar_events
                    WHERE start_time >= ? AND start_time <= ?
                      AND id NOT IN ({placeholders})""",
                [time_min, time_max, *fetched_ids],
            )
        else:
            # API returned zero events — clear everything in the window
            db.execute(
                """DELETE FROM calendar_events
                   WHERE start_time >= ? AND start_time <= ?""",
                [time_min, time_max],
            )
        db.commit()

    return len(events)
