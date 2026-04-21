"""Glance — family activity tracking module.

Endpoints:
  GET /api/glance/weeks?start=YYYY-MM-DD&end=YYYY-MM-DD  — day-keyed calendar data
  GET /api/glance/trips/{trip_id}                         — single trip with days array
  GET /api/glance/entries/{entry_id}                      — single entry
  GET /api/glance/members                                 — all members in sort order
  GET /api/glance/locations                               — all locations alphabetically
"""

import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_db_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/glance", tags=["glance"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_range(start: date, end: date) -> list[date]:
    """Return every date from start through end inclusive."""
    days = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days


def _row_to_dict(row) -> dict:
    return dict(row)


# ---------------------------------------------------------------------------
# GET /members
# ---------------------------------------------------------------------------

@router.get("/members")
def get_members():
    """All members ordered by sort_order."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT * FROM glance_members ORDER BY sort_order"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /locations
# ---------------------------------------------------------------------------

@router.get("/locations")
def get_locations():
    """All locations ordered alphabetically by display name."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT * FROM glance_locations ORDER BY display"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /trips/{trip_id}
# ---------------------------------------------------------------------------

@router.get("/trips/{trip_id}")
def get_trip(trip_id: int):
    """Single trip with full days array sorted by date."""
    with get_db_connection(readonly=True) as db:
        trip = db.execute(
            "SELECT * FROM glance_trips WHERE id = ?", (trip_id,)
        ).fetchone()
        if trip is None:
            raise HTTPException(status_code=404, detail="Trip not found")

        days = db.execute(
            'SELECT * FROM glance_trip_days WHERE trip_id = ? ORDER BY date',
            (trip_id,)
        ).fetchall()

    result = _row_to_dict(trip)
    result["days"] = [_row_to_dict(d) for d in days]
    return result


# ---------------------------------------------------------------------------
# GET /entries/{entry_id}
# ---------------------------------------------------------------------------

@router.get("/entries/{entry_id}")
def get_entry(entry_id: int):
    """Single entry by ID."""
    with get_db_connection(readonly=True) as db:
        entry = db.execute(
            "SELECT * FROM glance_entries WHERE id = ?", (entry_id,)
        ).fetchone()
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

    Each day value:
    {
      "trips":   [ { trip day data + member + location info } ],
      "entries": [ { entry data + optional member info } ],
      "gcal":    []   // always empty in Phase 1
    }
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
        # --- Members map ---
        members = {
            r["id"]: _row_to_dict(r)
            for r in db.execute("SELECT * FROM glance_members").fetchall()
        }

        # --- Locations map ---
        locations = {
            r["id"]: _row_to_dict(r)
            for r in db.execute("SELECT * FROM glance_locations").fetchall()
        }

        # --- Trips overlapping the date range ---
        # A trip overlaps if trip.start_date <= end AND trip.end_date >= start
        trip_rows = db.execute(
            """
            SELECT t.id, t.member_id, t.location_id,
                   t.start_date, t.end_date, t.notes,
                   t.source, t.source_ref
            FROM glance_trips t
            WHERE t.start_date <= ? AND t.end_date >= ?
            ORDER BY t.id
            """,
            (end, start),
        ).fetchall()

        trip_ids = [r["id"] for r in trip_rows]
        trip_map = {r["id"]: _row_to_dict(r) for r in trip_rows}

        # --- Trip days for those trips ---
        trip_day_map: dict[tuple, dict] = {}   # (trip_id, date_str) -> day row
        if trip_ids:
            placeholders = ",".join("?" * len(trip_ids))
            day_rows = db.execute(
                f"""
                SELECT id, trip_id, date, depart, sleep, "return", notes
                FROM glance_trip_days
                WHERE trip_id IN ({placeholders})
                ORDER BY date
                """,
                trip_ids,
            ).fetchall()
            for dr in day_rows:
                trip_day_map[(dr["trip_id"], dr["date"])] = _row_to_dict(dr)

        # --- Entries in range ---
        entry_rows = db.execute(
            """
            SELECT e.id, e.lane, e.member_id, e.date, e.label, e.notes
            FROM glance_entries e
            WHERE e.date >= ? AND e.date <= ?
            ORDER BY e.date, e.id
            """,
            (start, end),
        ).fetchall()

    # --- Build per-day result ---
    result: dict[str, dict] = {}

    for d in all_days:
        date_str = d.isoformat()
        result[date_str] = {"trips": [], "entries": [], "gcal": []}

    # Populate trip entries
    for trip in trip_map.values():
        member_id = trip["member_id"]
        location_id = trip["location_id"]
        member = members.get(member_id, {})
        location = locations.get(location_id, {})

        # Compute lane
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
                "location_id": location_id,
                "location_display": location.get("display"),
                "location_color_bg": location.get("color_bg"),
                "location_color_text": location.get("color_text"),
                "trip_id": trip_id,
                "trip_start": trip["start_date"],
                "trip_end": trip["end_date"],
                "trip_notes": trip.get("notes"),
                "depart": bool(day_data.get("depart", False)),
                "sleep": bool(day_data.get("sleep", False)),
                "return": bool(day_data.get("return", False)),
                "day_notes": day_data.get("notes"),
            })

    # Sort trips within each day by member sort_order
    member_order = {m_id: m["sort_order"] for m_id, m in members.items()}
    for date_str in result:
        result[date_str]["trips"].sort(key=lambda t: member_order.get(t["member_id"], 99))

    # Populate entries
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
        })

    return result
