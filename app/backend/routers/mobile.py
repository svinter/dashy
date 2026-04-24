"""Mobile API — endpoints for the Mobly PWA companion app.

Auth endpoints:
  POST /api/mobile/auth/login   — accept password, set session cookie
  POST /api/mobile/auth/logout  — clear session cookie
  GET  /api/mobile/auth/me      — session validity check

Data endpoints (require valid session):
  GET /api/mobile/libby         — current library loans
  GET /api/mobile/glance        — current week's Glance grid
"""

import hashlib
import logging
import secrets
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel

from app_config import load_config
from database import get_db_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobile", tags=["mobile"])

# ---------------------------------------------------------------------------
# Session tokens stored in memory — simple, no persistence needed.
# On server restart users re-login; cookies last 90 days regardless.
# ---------------------------------------------------------------------------

_active_tokens: set[str] = set()

_SESSION_COOKIE = "mobly_session"
_COOKIE_MAX_AGE = 90 * 24 * 60 * 60  # 90 days in seconds


def _get_password_hash() -> Optional[str]:
    cfg = load_config()
    return cfg.get("mobile_password_hash")


def _check_token(token: Optional[str]) -> bool:
    return bool(token and token in _active_tokens)


# ---------------------------------------------------------------------------
# Auth — POST /api/mobile/auth/login
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    password: str


@router.post("/auth/login")
def mobile_login(body: LoginRequest, response: Response):
    stored_hash = _get_password_hash()
    if not stored_hash:
        raise HTTPException(status_code=503, detail="Mobile auth not configured. Set mobile_password_hash in config.json.")

    incoming_hash = hashlib.sha256(body.password.encode()).hexdigest()
    if not secrets.compare_digest(incoming_hash, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid password")

    token = secrets.token_hex(32)
    _active_tokens.add(token)

    response.set_cookie(
        key=_SESSION_COOKIE,
        value=token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=False,  # Allow HTTP on tailnet; Tailscale Serve handles TLS termination
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Auth — POST /api/mobile/auth/logout
# ---------------------------------------------------------------------------

@router.post("/auth/logout")
def mobile_logout(response: Response, mobly_session: Optional[str] = Cookie(default=None)):
    if mobly_session and mobly_session in _active_tokens:
        _active_tokens.discard(mobly_session)
    response.delete_cookie(_SESSION_COOKIE)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Auth — GET /api/mobile/auth/me
# ---------------------------------------------------------------------------

@router.get("/auth/me")
def mobile_me(mobly_session: Optional[str] = Cookie(default=None)):
    if not _check_token(mobly_session):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"authenticated": True}


# ---------------------------------------------------------------------------
# Auth — POST /api/mobile/auth/set-password  (one-time setup)
# ---------------------------------------------------------------------------

class SetPasswordRequest(BaseModel):
    password: str


@router.post("/auth/set-password")
def mobile_set_password(body: SetPasswordRequest):
    """Store a new mobile password hash in config.json. Call once during setup."""
    from app_config import load_config, save_config
    cfg = load_config()
    cfg["mobile_password_hash"] = hashlib.sha256(body.password.encode()).hexdigest()
    save_config(cfg)
    return {"ok": True}


# ---------------------------------------------------------------------------
# GET /api/mobile/libby — current library loans
# ---------------------------------------------------------------------------

@router.get("/libby")
def mobile_libby(mobly_session: Optional[str] = Cookie(default=None)):
    if not _check_token(mobly_session):
        raise HTTPException(status_code=401, detail="Not authenticated")

    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            """
            SELECT
                e.id,
                e.name,
                e.type_code,
                e.loan_due_date,
                COALESCE(lb.author, lb.authors, li.author) AS author,
                lb.cover_url,
                lt.name AS type_label
            FROM library_entries e
            LEFT JOIN library_books lb ON e.type_code = 'b' AND lb.id = e.entity_id
            LEFT JOIN library_items li ON e.type_code != 'b' AND li.id = e.entity_id
            LEFT JOIN library_types lt ON lt.code = e.type_code
            WHERE e.on_loan = 1
            ORDER BY e.loan_due_date ASC NULLS LAST, e.name ASC
            """
        ).fetchall()

    today = date.today()
    items = []
    for row in rows:
        due = row["loan_due_date"]
        days_left = None
        if due:
            try:
                due_date = date.fromisoformat(due)
                days_left = (due_date - today).days
            except ValueError:
                pass

        items.append({
            "id": row["id"],
            "name": row["name"],
            "type_code": row["type_code"],
            "type_label": row["type_label"],
            "author": row["author"],
            "cover_url": row["cover_url"],
            "loan_due_date": due,
            "days_left": days_left,
        })

    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# GET /api/mobile/glance — current week's Glance grid
# ---------------------------------------------------------------------------

@router.get("/glance")
def mobile_glance(mobly_session: Optional[str] = Cookie(default=None)):
    if not _check_token(mobly_session):
        raise HTTPException(status_code=401, detail="Not authenticated")

    today = date.today()
    # Monday of the current week
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    with get_db_connection(readonly=True) as db:
        members = [dict(r) for r in db.execute("SELECT * FROM glance_members ORDER BY sort_order").fetchall()]

        trip_rows = db.execute(
            """
            SELECT t.id, t.member_id, t.location_id,
                   t.start_date, t.end_date, t.notes, t.color_data, t.text_color
            FROM glance_trips t
            WHERE t.start_date <= ? AND t.end_date >= ?
            ORDER BY t.id
            """,
            (week_end.isoformat(), week_start.isoformat()),
        ).fetchall()

        locations = {r["id"]: dict(r) for r in db.execute("SELECT * FROM glance_locations").fetchall()}

        entry_rows = db.execute(
            """
            SELECT e.id, e.lane, e.member_id, e.date, e.label, e.notes,
                   e.color_data, e.text_color
            FROM glance_entries e
            WHERE e.date >= ? AND e.date <= ?
            ORDER BY e.date, e.id
            """,
            (week_start.isoformat(), week_end.isoformat()),
        ).fetchall()

        comment_rows = db.execute(
            "SELECT lane_id, comment FROM glance_week_comments WHERE week_start = ?",
            (week_start.isoformat(),),
        ).fetchall()

    # Build day-keyed structure
    days = {}
    current = week_start
    while current <= week_end:
        days[current.isoformat()] = {"entries": [], "trips": []}
        current += timedelta(days=1)

    for entry in entry_rows:
        d = entry["date"]
        if d in days:
            days[d]["entries"].append({
                "id": entry["id"],
                "lane": entry["lane"],
                "member_id": entry["member_id"],
                "label": entry["label"],
                "notes": entry["notes"],
                "color_data": entry["color_data"],
                "text_color": entry["text_color"],
            })

    for trip in trip_rows:
        loc = locations.get(trip["location_id"], {}) if trip["location_id"] else {}
        trip_data = {
            "id": trip["id"],
            "member_id": trip["member_id"],
            "location": loc.get("name", ""),
            "start_date": trip["start_date"],
            "end_date": trip["end_date"],
            "notes": trip["notes"],
            "color_data": trip["color_data"],
            "text_color": trip["text_color"],
        }
        # Attach trip to each day it covers within the week
        trip_start = date.fromisoformat(trip["start_date"])
        trip_end = date.fromisoformat(trip["end_date"])
        d = max(trip_start, week_start)
        while d <= min(trip_end, week_end):
            if d.isoformat() in days:
                days[d.isoformat()]["trips"].append(trip_data)
            d += timedelta(days=1)

    week_comments = {r["lane_id"]: r["comment"] for r in comment_rows}

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "members": members,
        "days": days,
        "week_comments": week_comments,
    }
