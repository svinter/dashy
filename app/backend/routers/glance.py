"""Glance — family activity tracking module.

Read endpoints:
  GET /api/glance/weeks?start=YYYY-MM-DD&end=YYYY-MM-DD
  GET /api/glance/trips/{trip_id}
  GET /api/glance/entries/{entry_id}
  GET /api/glance/members
  GET /api/glance/locations

Write endpoints (Phase 2):
  PUT  /api/glance/comments
  POST /api/glance/trips
  PUT  /api/glance/trips/{trip_id}
  DELETE /api/glance/trips/{trip_id}
  POST /api/glance/entries
  PUT  /api/glance/entries/{entry_id}
  DELETE /api/glance/entries/{entry_id}
"""

import logging
import sqlite3
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_db_connection
from models import (
    GlanceCommentUpsert,
    GlanceTripCreate,
    GlanceTripUpdate,
    GlanceEntriesCreate,
    GlanceEntryCreate,
    GlanceEntryUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/glance", tags=["glance"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _date_range(start: date, end: date) -> list[date]:
    """Every date from start through end inclusive."""
    days: list[date] = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days


def _row_to_dict(row) -> dict:
    return dict(row)


def _compute_default_marks(start: date, end: date) -> list[dict]:
    """Compute depart/sleep/return marks for each day in a trip range."""
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


def _build_trip_response(db, trip_id: int) -> dict:
    """Return the full trip dict with days array (used by POST / PUT / GET trips)."""
    trip = db.execute("SELECT * FROM glance_trips WHERE id = ?", (trip_id,)).fetchone()
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    days = db.execute(
        'SELECT id, trip_id, date, depart, sleep, "return", notes '
        "FROM glance_trip_days WHERE trip_id = ? ORDER BY date",
        (trip_id,),
    ).fetchall()
    result = _row_to_dict(trip)
    result["days"] = [_row_to_dict(d) for d in days]
    return result


# ---------------------------------------------------------------------------
# GET /members
# ---------------------------------------------------------------------------

@router.get("/members")
def get_members():
    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT * FROM glance_members ORDER BY sort_order").fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /locations
# ---------------------------------------------------------------------------

@router.get("/locations")
def get_locations():
    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT * FROM glance_locations ORDER BY display").fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /trips/{trip_id}
# ---------------------------------------------------------------------------

@router.get("/trips/{trip_id}")
def get_trip(trip_id: int):
    with get_db_connection(readonly=True) as db:
        result = _build_trip_response(db, trip_id)
    return result


# ---------------------------------------------------------------------------
# GET /entries/{entry_id}
# ---------------------------------------------------------------------------

@router.get("/entries/{entry_id}")
def get_entry(entry_id: int):
    with get_db_connection(readonly=True) as db:
        entry = db.execute("SELECT * FROM glance_entries WHERE id = ?", (entry_id,)).fetchone()
        if entry is None:
            raise HTTPException(status_code=404, detail="Entry not found")
    return _row_to_dict(entry)


# ---------------------------------------------------------------------------
# GET /weeks
# ---------------------------------------------------------------------------

@router.get("/weeks")
def get_weeks(
    start: str = Query(..., description="Start date ISO YYYY-MM-DD"),
    end: str = Query(..., description="End date ISO YYYY-MM-DD"),
):
    """
    Returns a JSON object keyed by ISO date string for every day in [start, end].

    Each day:  { "trips": [...], "entries": [...], "gcal": [] }
    Monday only also includes: { "week_comment": { lane_id: comment_text, ... } }
    """
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date: {exc}") from exc

    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end must be >= start")

    all_days = _date_range(start_date, end_date)

    with get_db_connection(readonly=True) as db:
        members = {r["id"]: _row_to_dict(r) for r in db.execute("SELECT * FROM glance_members").fetchall()}
        locations = {r["id"]: _row_to_dict(r) for r in db.execute("SELECT * FROM glance_locations").fetchall()}

        trip_rows = db.execute(
            """
            SELECT t.id, t.member_id, t.location_id,
                   t.start_date, t.end_date, t.notes, t.color_data,
                   t.source, t.source_ref
            FROM glance_trips t
            WHERE t.start_date <= ? AND t.end_date >= ?
            ORDER BY t.id
            """,
            (end, start),
        ).fetchall()

        trip_ids = [r["id"] for r in trip_rows]
        trip_map = {r["id"]: _row_to_dict(r) for r in trip_rows}

        trip_day_map: dict[tuple, dict] = {}
        if trip_ids:
            placeholders = ",".join("?" * len(trip_ids))
            day_rows = db.execute(
                f'SELECT id, trip_id, date, depart, sleep, "return", notes '
                f"FROM glance_trip_days WHERE trip_id IN ({placeholders}) ORDER BY date",
                trip_ids,
            ).fetchall()
            for dr in day_rows:
                trip_day_map[(dr["trip_id"], dr["date"])] = _row_to_dict(dr)

        entry_rows = db.execute(
            "SELECT e.id, e.lane, e.member_id, e.date, e.label, e.notes, e.color_data "
            "FROM glance_entries e WHERE e.date >= ? AND e.date <= ? ORDER BY e.date, e.id",
            (start, end),
        ).fetchall()

        # Week comments keyed by (week_start, lane_id)
        comment_rows = db.execute(
            "SELECT week_start, lane_id, comment FROM glance_week_comments "
            "WHERE week_start >= ? AND week_start <= ?",
            (start, end),
        ).fetchall()
        comments_map: dict[str, dict[str, str]] = {}
        for cr in comment_rows:
            ws = cr["week_start"]
            if ws not in comments_map:
                comments_map[ws] = {}
            comments_map[ws][cr["lane_id"]] = cr["comment"]

    result: dict[str, dict] = {}

    for d in all_days:
        date_str = d.isoformat()
        day: dict = {"trips": [], "entries": [], "gcal": []}
        # Attach week_comment only on Mondays (ISO weekday 1 = Monday)
        if d.weekday() == 0 and date_str in comments_map:
            day["week_comment"] = comments_map[date_str]
        result[date_str] = day

    # Populate trips
    member_order = {m_id: m["sort_order"] for m_id, m in members.items()}
    for trip in trip_map.values():
        member_id = trip["member_id"]
        location_id = trip["location_id"]
        member = members.get(member_id, {})
        location = locations.get(location_id, {})
        lane = "steve_travel" if member_id == "steve" else "fam_travel"

        trip_start = date.fromisoformat(trip["start_date"])
        trip_end = date.fromisoformat(trip["end_date"])

        for d in all_days:
            if not (trip_start <= d <= trip_end):
                continue
            date_str = d.isoformat()
            trip_id = trip["id"]
            day_data = trip_day_map.get((trip_id, date_str), {})

            result[date_str]["trips"].append({
                "id": trip_id,
                "lane": lane,
                "member_id": member_id,
                "member_display": member.get("display"),
                "member_color_bg": member.get("color_bg"),
                "member_color_text": member.get("color_text"),
                "member_travel_color_bg": member.get("travel_color_bg"),
                "member_travel_color_text": member.get("travel_color_text"),
                "location_id": location_id,
                "location_display": location.get("display"),
                "location_color_bg": location.get("color_bg"),
                "location_color_text": location.get("color_text"),
                "trip_id": trip_id,
                "trip_start": trip["start_date"],
                "trip_end": trip["end_date"],
                "trip_notes": trip.get("notes"),
                "color_data": trip.get("color_data"),
                "depart": bool(day_data.get("depart", False)),
                "sleep": bool(day_data.get("sleep", False)),
                "return": bool(day_data.get("return", False)),
                "day_notes": day_data.get("notes"),
            })

    for date_str in result:
        result[date_str]["trips"].sort(key=lambda t: member_order.get(t["member_id"], 99))

    for entry in entry_rows:
        date_str = entry["date"]
        if date_str not in result:
            continue
        member_id = entry["member_id"]
        member = members.get(member_id, {}) if member_id else {}
        result[date_str]["entries"].append({
            "id": entry["id"],
            "lane": entry["lane"],
            "member_id": member_id,
            "member_display": member.get("display") if member else None,
            "member_color_bg": member.get("color_bg") if member else None,
            "member_color_text": member.get("color_text") if member else None,
            "label": entry["label"],
            "notes": entry["notes"],
            "color_data": entry["color_data"],
        })

    return result


# ---------------------------------------------------------------------------
# PUT /comments  — upsert week comment
# ---------------------------------------------------------------------------

@router.put("/comments")
def upsert_comment(body: GlanceCommentUpsert):
    with get_db_connection() as db:
        db.execute(
            """
            INSERT INTO glance_week_comments (week_start, lane_id, comment, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(week_start, lane_id) DO UPDATE SET
              comment = excluded.comment,
              updated_at = CURRENT_TIMESTAMP
            """,
            (body.week_start, body.lane_id, body.comment),
        )
        db.commit()
    return {"week_start": body.week_start, "lane_id": body.lane_id, "comment": body.comment}


# ---------------------------------------------------------------------------
# POST /trips  — create trip with auto-computed day marks
# ---------------------------------------------------------------------------

DEFAULT_LOCATION_COLOR_BG   = "#EF997A"
DEFAULT_LOCATION_COLOR_TEXT = "#4A1B0C"


def _resolve_or_create_location(db, location_id: Optional[str], location_name: Optional[str]) -> str:
    """Return the resolved location_id, creating a new row if necessary."""
    if not location_id and not location_name:
        raise HTTPException(status_code=400, detail="Either location_id or location_name is required")

    if location_id:
        # Validate it exists
        row = db.execute("SELECT id FROM glance_locations WHERE id = ?", (location_id,)).fetchone()
        if row:
            return location_id
        # Fall through: treat as unknown — try to match by display name
        location_name = location_id

    # Try case-insensitive match against existing display names
    name = location_name.strip()
    row = db.execute(
        "SELECT id FROM glance_locations WHERE LOWER(display) = LOWER(?)", (name,)
    ).fetchone()
    if row:
        return row["id"]

    # Also try matching by id slug
    slug = name.lower().replace(" ", "-")
    row = db.execute("SELECT id FROM glance_locations WHERE id = ?", (slug,)).fetchone()
    if row:
        return slug

    # Create new location
    db.execute(
        "INSERT INTO glance_locations (id, display, color_bg, color_text, is_home, is_york) "
        "VALUES (?, ?, ?, ?, 0, 0)",
        (slug, name, DEFAULT_LOCATION_COLOR_BG, DEFAULT_LOCATION_COLOR_TEXT),
    )
    return slug


@router.post("/trips", status_code=201)
def create_trip(body: GlanceTripCreate):
    try:
        start = date.fromisoformat(body.start_date)
        end = date.fromisoformat(body.end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date: {exc}") from exc
    if end < start:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")

    marks = _compute_default_marks(start, end)
    if body.day_overrides:
        overrides = {o["date"]: o for o in body.day_overrides}
        for m in marks:
            if m["date"] in overrides:
                o = overrides[m["date"]]
                for key in ("depart", "sleep", "return", "notes"):
                    if key in o:
                        m[key] = o[key]

    try:
        with get_db_connection() as db:
            resolved_location_id = _resolve_or_create_location(db, body.location_id, body.location_name)
            cur = db.execute(
                "INSERT INTO glance_trips (member_id, location_id, start_date, end_date, notes, color_data, source) "
                "VALUES (?, ?, ?, ?, ?, ?, 'manual')",
                (body.member_id, resolved_location_id, body.start_date, body.end_date, body.notes, body.color_data),
            )
            trip_id = cur.lastrowid
            for m in marks:
                db.execute(
                    'INSERT INTO glance_trip_days (trip_id, date, depart, sleep, "return", notes) '
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (trip_id, m["date"], m["depart"], m["sleep"], m["return"], m.get("notes")),
                )
            db.commit()
            result = _build_trip_response(db, trip_id)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid member_id or location_id: {exc}") from exc
    return result


# ---------------------------------------------------------------------------
# PUT /trips/{trip_id}  — update trip, recompute days on resize
# ---------------------------------------------------------------------------

@router.put("/trips/{trip_id}")
def update_trip(trip_id: int, body: GlanceTripUpdate):
    with get_db_connection() as db:
        trip = db.execute("SELECT * FROM glance_trips WHERE id = ?", (trip_id,)).fetchone()
        if trip is None:
            raise HTTPException(status_code=404, detail="Trip not found")

        new_start_str = body.start_date or trip["start_date"]
        new_end_str = body.end_date or trip["end_date"]
        try:
            new_start = date.fromisoformat(new_start_str)
            new_end = date.fromisoformat(new_end_str)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid date: {exc}") from exc
        if new_end < new_start:
            raise HTTPException(status_code=400, detail="end_date must be >= start_date")

        old_start = date.fromisoformat(trip["start_date"])
        old_end = date.fromisoformat(trip["end_date"])
        resized = (new_start != old_start) or (new_end != old_end)

        # Update trip fields
        updates: list = []
        params: list = []
        if body.member_id is not None:
            updates.append("member_id = ?"); params.append(body.member_id)
        if body.location_id is not None or body.location_name is not None:
            resolved = _resolve_or_create_location(db, body.location_id, body.location_name)
            updates.append("location_id = ?"); params.append(resolved)
        if body.start_date is not None:
            updates.append("start_date = ?"); params.append(body.start_date)
        if body.end_date is not None:
            updates.append("end_date = ?"); params.append(body.end_date)
        if body.notes is not None:
            updates.append("notes = ?"); params.append(body.notes)
        if body.color_data is not None:
            updates.append("color_data = ?"); params.append(body.color_data)
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(trip_id)
        db.execute(f"UPDATE glance_trips SET {', '.join(updates)} WHERE id = ?", params)

        if resized:
            # Delete days outside new range
            db.execute(
                "DELETE FROM glance_trip_days WHERE trip_id = ? AND (date < ? OR date > ?)",
                (trip_id, new_start_str, new_end_str),
            )
            # Add newly covered days with default marks
            existing_dates = {
                r["date"]
                for r in db.execute(
                    "SELECT date FROM glance_trip_days WHERE trip_id = ?", (trip_id,)
                ).fetchall()
            }
            new_marks = _compute_default_marks(new_start, new_end)
            for m in new_marks:
                if m["date"] not in existing_dates:
                    db.execute(
                        'INSERT INTO glance_trip_days (trip_id, date, depart, sleep, "return", notes) '
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (trip_id, m["date"], m["depart"], m["sleep"], m["return"], None),
                    )
            # Enforce depart=True only on new start, return=True only on new end
            if new_start != old_start:
                db.execute(
                    "UPDATE glance_trip_days SET depart = 0 WHERE trip_id = ? AND date != ?",
                    (trip_id, new_start_str),
                )
                db.execute(
                    "UPDATE glance_trip_days SET depart = 1 WHERE trip_id = ? AND date = ?",
                    (trip_id, new_start_str),
                )
            if new_end != old_end:
                db.execute(
                    'UPDATE glance_trip_days SET "return" = 0 WHERE trip_id = ? AND date != ?',
                    (trip_id, new_end_str),
                )
                db.execute(
                    'UPDATE glance_trip_days SET "return" = 1 WHERE trip_id = ? AND date = ?',
                    (trip_id, new_end_str),
                )

        if body.day_overrides:
            for o in body.day_overrides:
                sets: list = []
                sparams: list = []
                for key in ("depart", "sleep", "return", "notes"):
                    if key in o:
                        col = f'"{key}"' if key == "return" else key
                        sets.append(f"{col} = ?")
                        sparams.append(o[key])
                if sets:
                    sparams.extend([trip_id, o["date"]])
                    db.execute(
                        f"UPDATE glance_trip_days SET {', '.join(sets)} "
                        "WHERE trip_id = ? AND date = ?",
                        sparams,
                    )

        db.commit()
        result = _build_trip_response(db, trip_id)
    return result


# ---------------------------------------------------------------------------
# DELETE /trips/{trip_id}
# ---------------------------------------------------------------------------

@router.delete("/trips/{trip_id}", status_code=204)
def delete_trip(trip_id: int):
    with get_db_connection() as db:
        existing = db.execute("SELECT id FROM glance_trips WHERE id = ?", (trip_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Trip not found")
        # ON DELETE CASCADE handles trip_days
        db.execute("DELETE FROM glance_trips WHERE id = ?", (trip_id,))
        db.commit()


# ---------------------------------------------------------------------------
# POST /entries  — create one or more entries (batch)
# ---------------------------------------------------------------------------

@router.post("/entries", status_code=201)
def create_entries(body: GlanceEntriesCreate):
    created = []
    with get_db_connection() as db:
        for e in body.entries:
            cur = db.execute(
                "INSERT INTO glance_entries (lane, member_id, date, label, notes, color_data, source) "
                "VALUES (?, ?, ?, ?, ?, ?, 'manual')",
                (e.lane, e.member_id, e.date, e.label, e.notes, e.color_data),
            )
            entry_id = cur.lastrowid
            row = db.execute("SELECT * FROM glance_entries WHERE id = ?", (entry_id,)).fetchone()
            created.append(_row_to_dict(row))
        db.commit()
    return created


# ---------------------------------------------------------------------------
# PUT /entries/{entry_id}
# ---------------------------------------------------------------------------

@router.put("/entries/{entry_id}")
def update_entry(entry_id: int, body: GlanceEntryUpdate):
    with get_db_connection() as db:
        existing = db.execute("SELECT * FROM glance_entries WHERE id = ?", (entry_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Entry not found")

        updates: list = []
        params: list = []
        if body.lane is not None:
            updates.append("lane = ?"); params.append(body.lane)
        if body.member_id is not None:
            updates.append("member_id = ?"); params.append(body.member_id)
        if body.date is not None:
            updates.append("date = ?"); params.append(body.date)
        if body.label is not None:
            updates.append("label = ?"); params.append(body.label)
        if body.notes is not None:
            updates.append("notes = ?"); params.append(body.notes)
        if body.color_data is not None:
            updates.append("color_data = ?"); params.append(body.color_data)
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(entry_id)
        db.execute(f"UPDATE glance_entries SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()
        row = db.execute("SELECT * FROM glance_entries WHERE id = ?", (entry_id,)).fetchone()
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# DELETE /entries/{entry_id}
# ---------------------------------------------------------------------------

@router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int):
    with get_db_connection() as db:
        existing = db.execute("SELECT id FROM glance_entries WHERE id = ?", (entry_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        db.execute("DELETE FROM glance_entries WHERE id = ?", (entry_id,))
        db.commit()
