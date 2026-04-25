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
import io
import logging
import re as _re
import secrets
import time
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel

from app_config import load_config
from database import get_db_connection
from routers.libby import _parse_query, _TYPE_NAMES, _cover_from_asin

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
        samesite="lax",   # lax allows cookie on same-site navigations incl. Tailscale HTTP
        secure=False,
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
# GET /api/mobile/libby/search — search library (or recent if q is empty)
# ---------------------------------------------------------------------------

@router.get("/libby/search")
def mobile_libby_search(
    q: str = "",
    limit: int = 20,
    mobly_session: Optional[str] = Cookie(default=None),
):
    if not _check_token(mobly_session):
        raise HTTPException(status_code=401, detail="Not authenticated")

    with get_db_connection(readonly=True) as db:
        if not q.strip():
            rows = db.execute(
                """
                SELECT
                    e.id, e.name, e.type_code, e.url, e.amazon_short_url, e.comments,
                    COALESCE(e.amazon_short_url, e.amazon_url) AS amazon_url,
                    COALESCE(lb.author, li.author) AS author,
                    COALESCE(e.cover_url, lb.cover_url) AS cover_url,
                    lb.isbn,
                    li.notes AS synopsis
                FROM library_entries e
                LEFT JOIN library_books lb ON e.type_code = 'b' AND lb.id = e.entity_id
                LEFT JOIN library_items li ON e.type_code != 'b' AND li.id = e.entity_id
                ORDER BY e.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            type_code, topic_prefixes, name_tokens = _parse_query(q)
            sql = """
                SELECT
                    e.id, e.name, e.type_code, e.url, e.amazon_short_url, e.comments,
                    COALESCE(e.amazon_short_url, e.amazon_url) AS amazon_url,
                    COALESCE(lb.author, li.author) AS author,
                    COALESCE(e.cover_url, lb.cover_url) AS cover_url,
                    lb.isbn,
                    li.notes AS synopsis
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
                        OR (e.type_code = 'b' AND lower(lb.author) LIKE ?)
                    )
                """
                params.extend([f"%{tok}%", f"%{tok}%"])

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

            sql += " ORDER BY e.id DESC LIMIT ?"
            params.append(limit)

            rows = db.execute(sql, params).fetchall()

    _pending_covers: list[tuple[str, int]] = []
    items = []
    for row in rows:
        cover_url: str | None = row["cover_url"]
        if cover_url is None:
            derived = _cover_from_asin(row["amazon_url"])
            if not derived and row["isbn"]:
                derived = f"https://covers.openlibrary.org/b/isbn/{row['isbn']}-M.jpg"
            if derived:
                cover_url = derived
                _pending_covers.append((derived, row["id"]))
        items.append({
            "id": row["id"],
            "name": row["name"],
            "type_code": row["type_code"],
            "type_label": _TYPE_NAMES.get(row["type_code"], row["type_code"].upper()),
            "author": row["author"],
            "cover_url": cover_url,
            "synopsis": row["synopsis"],
            "url": row["url"],
            "amazon_url": row["amazon_url"],
            "amazon_short_url": row["amazon_short_url"],
            "comments": row["comments"],
        })

    if _pending_covers:
        with get_db_connection() as wdb:
            for _cov, _eid in _pending_covers:
                wdb.execute(
                    "UPDATE library_entries SET cover_url = ? WHERE id = ? AND cover_url IS NULL",
                    (_cov, _eid),
                )
            wdb.commit()

    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# GET /api/mobile/libby/exists — check if a title already exists (pre-lookup)
# ---------------------------------------------------------------------------

@router.get("/libby/exists")
def mobile_libby_exists(
    name: str,
    mobly_session: Optional[str] = Cookie(default=None),
):
    if not _check_token(mobly_session):
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not name.strip():
        return {"exists": False}
    with get_db_connection(readonly=True) as db:
        row = db.execute(
            "SELECT id, name FROM library_entries WHERE lower(name) = lower(?) LIMIT 1",
            (name.strip(),),
        ).fetchone()
    if row:
        return {"exists": True, "existing_id": row["id"], "existing_name": row["name"]}
    return {"exists": False}


# ---------------------------------------------------------------------------
# POST /api/mobile/libby/add — quick-add a library entry by URL or title
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# POST /api/mobile/libby/lookup — search Google Books, return preview (no save)
# ---------------------------------------------------------------------------

class LibbyLookupRequest(BaseModel):
    name: str


@router.post("/libby/lookup")
def mobile_libby_lookup(
    body: LibbyLookupRequest,
    mobly_session: Optional[str] = Cookie(default=None),
):
    if not _check_token(mobly_session):
        raise HTTPException(status_code=401, detail="Not authenticated")

    raw = body.name.strip()
    if not raw:
        raise HTTPException(status_code=422, detail="name is required")

    # URLs skip Google Books lookup
    if _re.match(r"https?://", raw):
        return {"matched": False, "is_url": True, "name": raw, "author": None, "cover_url": None, "isbn": None, "info_link": None}

    try:
        from pipeline.sources.enrich import _query_gbooks
        data = _query_gbooks(raw, "")
    except Exception as exc:
        logger.warning("Google Books lookup failed for %r: %s", raw, exc)
        data = None

    if data:
        vol_info = data.get("volumeInfo", {})
        authors_list = vol_info.get("authors") or []
        author = authors_list[0] if authors_list else None
        image_links = vol_info.get("imageLinks") or {}
        raw_cover = image_links.get("thumbnail") or image_links.get("smallThumbnail") or ""
        cover_url = raw_cover.replace("http://", "https://", 1) if raw_cover else None
        isbn_map = {d["type"]: d["identifier"] for d in vol_info.get("industryIdentifiers", [])}
        isbn = isbn_map.get("ISBN_13") or isbn_map.get("ISBN_10")
        info_link = vol_info.get("infoLink")
        return {
            "matched": True,
            "is_url": False,
            "name": vol_info.get("title", raw),
            "author": author,
            "cover_url": cover_url,
            "isbn": isbn,
            "info_link": info_link,
        }

    return {"matched": False, "is_url": False, "name": raw, "author": None, "cover_url": None, "isbn": None, "info_link": None}


# ---------------------------------------------------------------------------
# POST /api/mobile/libby/add — save a book entry (after lookup preview)
# ---------------------------------------------------------------------------

_VALID_TYPE_CODES = {"b", "a", "v", "p", "e", "m", "t", "s", "z", "n", "d", "f", "c", "r", "q"}


class LibbyAddRequest(BaseModel):
    name: str
    author: Optional[str] = None
    cover_url: Optional[str] = None
    isbn: Optional[str] = None
    notes: Optional[str] = None
    type_code: Optional[str] = None
    url: Optional[str] = None
    amazon_url: Optional[str] = None
    force: bool = False


@router.post("/libby/add")
def mobile_libby_add(
    body: LibbyAddRequest,
    mobly_session: Optional[str] = Cookie(default=None),
):
    if not _check_token(mobly_session):
        raise HTTPException(status_code=401, detail="Not authenticated")

    raw = body.name.strip()
    if not raw:
        raise HTTPException(status_code=422, detail="name is required")

    is_url = bool(_re.match(r"https?://", raw))
    url = raw if is_url else None

    if is_url:
        type_code = "w"
    elif body.type_code and body.type_code in _VALID_TYPE_CODES:
        type_code = body.type_code
    else:
        type_code = "b"

    with get_db_connection() as db:
        if not body.force:
            existing = db.execute(
                "SELECT id, name FROM library_entries WHERE lower(name) = lower(?) LIMIT 1",
                (raw,),
            ).fetchone()
            if existing:
                return {
                    "duplicate": True,
                    "existing_id": existing["id"],
                    "existing_name": existing["name"],
                }
        notes = body.notes.strip() if body.notes and body.notes.strip() else None
        if is_url or type_code != "b":
            item_cur = db.execute("INSERT INTO library_items DEFAULT VALUES")
            entity_id = item_cur.lastrowid
            entry_cur = db.execute(
                "INSERT INTO library_entries (name, type_code, url, amazon_url, entity_id, comments) VALUES (?, ?, ?, ?, ?, ?)",
                (raw, type_code, url or body.url, body.amazon_url, entity_id, notes),
            )
        else:
            book_cur = db.execute(
                "INSERT INTO library_books (author, isbn, cover_url) VALUES (?, ?, ?)",
                (body.author, body.isbn, body.cover_url),
            )
            entity_id = book_cur.lastrowid
            entry_cur = db.execute(
                "INSERT INTO library_entries (name, type_code, entity_id, cover_url, url, amazon_url, comments) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (raw, type_code, entity_id, body.cover_url, body.url, body.amazon_url, notes),
            )
        entry_id = entry_cur.lastrowid
        db.commit()

    return {
        "id": entry_id,
        "name": raw,
        "type_code": type_code,
        "type_label": _TYPE_NAMES.get(type_code, type_code.upper()),
        "author": body.author,
        "cover_url": body.cover_url,
    }


# ---------------------------------------------------------------------------
# PATCH /api/mobile/libby/{entry_id}/notes — update comments on an entry
# ---------------------------------------------------------------------------

class LibbyNotesRequest(BaseModel):
    comments: Optional[str] = None


@router.patch("/libby/{entry_id}/notes")
def mobile_libby_notes(
    entry_id: int,
    body: LibbyNotesRequest,
    mobly_session: Optional[str] = Cookie(default=None),
):
    if not _check_token(mobly_session):
        raise HTTPException(status_code=401, detail="Not authenticated")

    comments = body.comments.strip() if body.comments and body.comments.strip() else None
    with get_db_connection() as db:
        cur = db.execute(
            "UPDATE library_entries SET comments = ? WHERE id = ?",
            (comments, entry_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Not found")
        db.commit()
    return {"ok": True, "comments": comments}


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


# ---------------------------------------------------------------------------
# GET /api/mobile/glance/render — PIL-rendered PNG of the Glance grid
# ---------------------------------------------------------------------------

_render_cache: dict[tuple, tuple[bytes, float]] = {}
_RENDER_CACHE_TTL = 300  # 5 minutes


def _parse_hex(h: Optional[str]) -> Optional[tuple]:
    if not h or not h.startswith("#") or len(h) != 7:
        return None
    try:
        return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))
    except ValueError:
        return None


def _luminance(rgb: tuple) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _auto_text(bg: tuple) -> tuple:
    return (255, 255, 255) if _luminance(bg) < 140 else (15, 23, 42)


_font_cache: dict[int, object] = {}


def _load_font(size: int):
    if size in _font_cache:
        return _font_cache[size]
    from PIL import ImageFont
    for path in [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        try:
            f = ImageFont.truetype(path, size)
            _font_cache[size] = f
            return f
        except (IOError, OSError):
            continue
    f = ImageFont.load_default()
    _font_cache[size] = f
    return f


def _render_glance_png(
    start_date: date,
    total_days: int,
    members: list,
    trip_rows: list,
    entry_rows: list,
    locations: dict,
) -> bytes:
    from PIL import Image, ImageDraw

    # ── palette ──────────────────────────────────────────────────────────────
    C_BG = (15, 23, 42)
    C_HEADER = (22, 33, 55)
    C_LABEL = (71, 85, 105)
    C_GRID = (37, 51, 71)
    C_MONTH_LINE = (239, 68, 68)       # red-ish boundary
    C_TODAY_HL = (20, 40, 80)          # subtle blue column highlight
    C_TODAY_RING = (59, 130, 246)      # blue ring for today number
    C_DATE_FG = (241, 245, 249)
    C_DATE_MUT = (100, 116, 139)
    C_ACCENT = (59, 130, 246)
    C_DEFAULT_PILL = (51, 65, 85)

    W = 1200
    LABEL_W = 82
    GRID_W = W - LABEL_W
    ROW_H_DATE = 38
    ROW_H_LANE = 28
    ROW_H_TRIP = 28
    PILL_H = 17
    PILL_PAD_Y = 6
    PILL_RADIUS = 4
    PILL_GAP = 2
    FONT_SM = _load_font(10)
    FONT_MD = _load_font(12)

    col_w = GRID_W / total_days
    today = date.today()

    # ── lane definitions ─────────────────────────────────────────────────────
    LANE_ORDER = ["york", "fam_events", "steve_events"]
    LANE_LABELS = {"york": "York", "fam_events": "Family", "steve_events": "Steve"}

    # ── organize entries by lane → date → list ───────────────────────────────
    lane_data: dict[str, dict[str, list]] = {}
    for e in entry_rows:
        lane = e["lane"]
        lane_data.setdefault(lane, {}).setdefault(e["date"], []).append(e)

    lanes_present = [l for l in LANE_ORDER if l in lane_data]
    # include any extra lanes not in LANE_ORDER
    for l in lane_data:
        if l not in lanes_present:
            lanes_present.append(l)

    # ── organize trips by member ─────────────────────────────────────────────
    member_by_id = {m["id"]: m for m in members}
    member_trips: dict[str, list] = {}
    for t in trip_rows:
        mid = t["member_id"]
        loc = locations.get(t["location_id"] or "", {}) if t["location_id"] else {}
        label = loc.get("display") or loc.get("name") or t["location_id"] or "trip"
        member_trips.setdefault(mid, []).append({
            "start": date.fromisoformat(t["start_date"]),
            "end": date.fromisoformat(t["end_date"]),
            "label": label,
            "color": _parse_hex(t["color_data"]),
            "text_color": _parse_hex(t["text_color"]),
        })

    # Only members that have trips in range
    trip_member_ids = [m["id"] for m in members if m["id"] in member_trips]

    # ── compute image height ──────────────────────────────────────────────────
    H = ROW_H_DATE + len(lanes_present) * ROW_H_LANE + len(trip_member_ids) * ROW_H_TRIP + 4

    img = Image.new("RGB", (W, H), C_BG)
    draw = ImageDraw.Draw(img)

    # ── today column highlight ────────────────────────────────────────────────
    if start_date <= today <= start_date + timedelta(days=total_days - 1):
        col_i = (today - start_date).days
        x0 = int(LABEL_W + col_i * col_w)
        x1 = int(LABEL_W + (col_i + 1) * col_w)
        draw.rectangle([x0, 0, x1, H], fill=C_TODAY_HL)

    # ── vertical grid lines ───────────────────────────────────────────────────
    for i in range(total_days + 1):
        x = int(LABEL_W + i * col_w)
        draw.line([(x, 0), (x, H)], fill=C_GRID, width=1)

    # ── month boundary lines ──────────────────────────────────────────────────
    for i in range(1, total_days):
        d = start_date + timedelta(days=i)
        if d.day == 1:
            x = int(LABEL_W + i * col_w)
            draw.line([(x, 0), (x, H)], fill=C_MONTH_LINE, width=2)

    # ── date header row ───────────────────────────────────────────────────────
    draw.rectangle([0, 0, W, ROW_H_DATE], fill=C_HEADER)
    for i in range(total_days):
        d = start_date + timedelta(days=i)
        x0 = int(LABEL_W + i * col_w)
        x1 = int(LABEL_W + (i + 1) * col_w)
        cx = (x0 + x1) // 2
        is_today = d == today

        dow = "MTWTFSS"[d.weekday()]
        day_n = str(d.day)
        top_label = d.strftime("%b") if d.day == 1 else dow
        top_color = C_ACCENT if (d.day == 1 and is_today) else (C_ACCENT if d.day == 1 else (C_DATE_FG if is_today else C_DATE_MUT))

        draw.text((cx, 5), top_label, fill=top_color, font=FONT_SM, anchor="mt")

        if is_today:
            r = 9
            draw.ellipse([cx - r, 18, cx + r, 18 + r * 2], fill=C_TODAY_RING)
            draw.text((cx, 19), day_n, fill=(255, 255, 255), font=FONT_MD, anchor="mt")
        else:
            draw.text((cx, 19), day_n, fill=C_DATE_FG if d.day == 1 else C_DATE_MUT, font=FONT_MD, anchor="mt")

    # ── lane rows ─────────────────────────────────────────────────────────────
    y = ROW_H_DATE
    for lane in lanes_present:
        draw.line([(0, y), (W, y)], fill=C_GRID, width=1)
        label = LANE_LABELS.get(lane, lane)
        draw.text((LABEL_W // 2, y + ROW_H_LANE // 2), label, fill=C_LABEL, font=FONT_SM, anchor="mm")

        for i in range(total_days):
            d = start_date + timedelta(days=i)
            cells = lane_data.get(lane, {}).get(d.isoformat(), [])
            if not cells:
                continue

            x0 = int(LABEL_W + i * col_w) + 2
            x1 = int(LABEL_W + (i + 1) * col_w) - 2

            for j, cell in enumerate(cells[:2]):
                py0 = y + PILL_PAD_Y + j * (PILL_H + PILL_GAP)
                py1 = py0 + PILL_H
                if py1 > y + ROW_H_LANE - 2:
                    break

                pill_c = _parse_hex(cell["color_data"])
                if pill_c is None and cell["member_id"]:
                    m = member_by_id.get(cell["member_id"])
                    if m:
                        pill_c = _parse_hex(m["color_bg"])
                pill_c = pill_c or C_DEFAULT_PILL

                draw.rounded_rectangle([x0, py0, x1, py1], radius=PILL_RADIUS, fill=pill_c)

                text_c = _parse_hex(cell["text_color"]) or _auto_text(pill_c)
                entry_label = (cell["label"] or "").strip()
                max_chars = max(1, int((x1 - x0 - 4) / 6))
                if len(entry_label) > max_chars:
                    entry_label = entry_label[:max_chars - 1] + "…"
                draw.text(((x0 + x1) // 2, (py0 + py1) // 2), entry_label,
                          fill=text_c, font=FONT_SM, anchor="mm")

        y += ROW_H_LANE

    # ── trip rows ─────────────────────────────────────────────────────────────
    end_date = start_date + timedelta(days=total_days - 1)
    for mid in trip_member_ids:
        draw.line([(0, y), (W, y)], fill=C_GRID, width=1)
        m = member_by_id.get(mid, {})
        label = m.get("display") or mid
        draw.text((LABEL_W // 2, y + ROW_H_TRIP // 2), label, fill=C_LABEL, font=FONT_SM, anchor="mm")

        for trip in member_trips.get(mid, []):
            ts = max(trip["start"], start_date)
            te = min(trip["end"], end_date)
            if ts > te:
                continue

            col_s = (ts - start_date).days
            col_e = (te - start_date).days
            px0 = int(LABEL_W + col_s * col_w) + 2
            px1 = int(LABEL_W + (col_e + 1) * col_w) - 2
            py0 = y + PILL_PAD_Y
            py1 = py0 + PILL_H

            tc = trip["color"]
            if tc is None:
                tc = _parse_hex(m.get("travel_color_bg")) or _parse_hex(m.get("color_bg")) or C_DEFAULT_PILL

            draw.rounded_rectangle([px0, py0, px1, py1], radius=PILL_RADIUS, fill=tc)

            text_c = trip["text_color"] or _auto_text(tc)
            trip_label = trip["label"]
            max_chars = max(1, int((px1 - px0 - 4) / 6))
            if len(trip_label) > max_chars:
                trip_label = trip_label[:max_chars - 1] + "…"
            draw.text(((px0 + px1) // 2, (py0 + py1) // 2), trip_label,
                      fill=text_c, font=FONT_SM, anchor="mm")

        y += ROW_H_TRIP

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@router.get("/glance/render")
def mobile_glance_render(
    start: Optional[str] = None,
    weeks: int = 8,
    mobly_session: Optional[str] = Cookie(default=None),
):
    if not _check_token(mobly_session):
        raise HTTPException(status_code=401, detail="Not authenticated")

    today = date.today()
    if start:
        try:
            start_date = date.fromisoformat(start)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start date")
    else:
        # First Monday of current month
        first = date(today.year, today.month, 1)
        start_date = first - timedelta(days=first.weekday())

    weeks = max(1, min(weeks, 26))
    cache_key = (start_date.isoformat(), weeks)

    now = time.time()
    cached = _render_cache.get(cache_key)
    if cached and now - cached[1] < _RENDER_CACHE_TTL:
        return Response(content=cached[0], media_type="image/png",
                        headers={"Cache-Control": "no-store"})

    end_date = start_date + timedelta(days=weeks * 7 - 1)

    with get_db_connection(readonly=True) as db:
        members = [dict(r) for r in db.execute(
            "SELECT * FROM glance_members ORDER BY sort_order"
        ).fetchall()]

        trip_rows = [dict(r) for r in db.execute(
            """
            SELECT t.id, t.member_id, t.location_id,
                   t.start_date, t.end_date, t.notes, t.color_data, t.text_color
            FROM glance_trips t
            WHERE t.start_date <= ? AND t.end_date >= ?
            ORDER BY t.member_id, t.id
            """,
            (end_date.isoformat(), start_date.isoformat()),
        ).fetchall()]

        locations = {r["id"]: dict(r) for r in db.execute(
            "SELECT * FROM glance_locations"
        ).fetchall()}

        entry_rows = [dict(r) for r in db.execute(
            """
            SELECT e.id, e.lane, e.member_id, e.date, e.label, e.notes,
                   e.color_data, e.text_color
            FROM glance_entries e
            WHERE e.date >= ? AND e.date <= ?
            ORDER BY e.date, e.id
            """,
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()]

    png = _render_glance_png(
        start_date, weeks * 7, members, trip_rows, entry_rows, locations
    )
    _render_cache[cache_key] = (png, now)

    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})
