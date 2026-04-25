import json
import logging
import re
import threading
import traceback
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app_config import load_config
from database import get_db, get_write_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/coaching", tags=["coaching"])

# In-memory store for async client creation tasks {task_id → task_dict}
_client_tasks: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# GET /api/coaching/active — detect in-progress grape/banana session
# ---------------------------------------------------------------------------

@router.get("/active")
def get_coaching_active():
    """
    Returns the currently active coaching client/project if exactly one
    grape (color_id='3') or banana (color_id='5') calendar event overlaps now.
    Multiple simultaneous events → {active: false}.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    # Pull today's grape/banana events and filter by overlap in Python
    # (avoids timezone parsing issues in SQLite)
    rows = db.execute(
        """SELECT id, summary, start_time, end_time
           FROM calendar_events
           WHERE color_id IN ('3', '5')
             AND date(start_time) = ?
             AND (status IS NULL OR status != 'cancelled')""",
        (today,),
    ).fetchall()

    active_events = []
    for row in rows:
        try:
            start = datetime.fromisoformat(row["start_time"])
            end   = datetime.fromisoformat(row["end_time"])
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            start_utc = start.astimezone(timezone.utc)
            end_utc   = end.astimezone(timezone.utc)
            in_range  = start_utc <= now <= end_utc
            logger.info(
                "coaching/active candidate: summary=%r start_utc=%s end_utc=%s now_utc=%s in_range=%s",
                row["summary"], start_utc.isoformat(), end_utc.isoformat(), now.isoformat(), in_range,
            )
            if in_range:
                active_events.append(row)
        except (ValueError, TypeError) as exc:
            logger.warning("coaching/active: could not parse times for event %r: %s", row["id"], exc)

    if len(active_events) != 1:
        return {"active": False}

    event = active_events[0]

    # Try to match via billing_sessions.calendar_event_id
    session = db.execute(
        "SELECT client_id, project_id FROM billing_sessions WHERE calendar_event_id = ? LIMIT 1",
        (event["id"],),
    ).fetchone()

    if session and session["client_id"]:
        client = db.execute(
            """SELECT bc.id, bc.name, bc.obsidian_name
               FROM billing_clients bc WHERE bc.id = ?""",
            (session["client_id"],),
        ).fetchone()
        if client:
            return {
                "active": True,
                "type": "client",
                "client_id": client["id"],
                "project_id": None,
                "client_name": client["name"],
                "obsidian_name": client["obsidian_name"],
                "company_name": None,
            }

    if session and session["project_id"]:
        project = db.execute(
            """SELECT bp.id, bp.name, bp.obsidian_name, bco.name AS company_name
               FROM billing_projects bp
               JOIN billing_companies bco ON bp.company_id = bco.id
               WHERE bp.id = ?""",
            (session["project_id"],),
        ).fetchone()
        if project:
            return {
                "active": True,
                "type": "project",
                "client_id": None,
                "project_id": project["id"],
                "client_name": project["name"],
                "obsidian_name": project["obsidian_name"],
                "company_name": project["company_name"],
            }

    # Fallback: word-level fuzzy match of event summary against client and project names.
    # Splits on whitespace/punctuation; strips the coach's own name tokens to avoid
    # matching clients whose names share words with the coach (e.g. "Steve Renter").
    summary_raw = (event["summary"] or "")
    raw_tokens = set(re.split(r'[\s/,;:\-]+', summary_raw.lower()))
    # Remove coach's name tokens so "Steve/Vinny" won't match a client called "Steve X"
    try:
        cfg = load_config()
        coach_name = (cfg.get("profile", {}) or {}).get("user_name", "") or ""
    except Exception:
        coach_name = ""
    coach_tokens = {t.lower() for t in re.split(r'\s+', coach_name) if t}
    summary_tokens = raw_tokens - coach_tokens
    logger.info(
        "coaching/active fallback: event=%r raw_tokens=%r coach_tokens=%r effective_tokens=%r",
        summary_raw, raw_tokens, coach_tokens, summary_tokens,
    )

    def _word_match(name: str) -> bool:
        for word in re.split(r'[\s/,;:\-]+', name.lower()):
            if len(word) > 3 and word in summary_tokens:
                return True
        return False

    clients = db.execute(
        "SELECT id, name, obsidian_name FROM billing_clients WHERE status IN ('active', 'infrequent')"
    ).fetchall()
    matched_clients = [c for c in clients if _word_match(c["name"])]
    logger.info("coaching/active fallback: matched clients=%r", [c["name"] for c in matched_clients])

    projects = db.execute(
        """SELECT bp.id, bp.name, bp.obsidian_name, bco.name AS company_name
           FROM billing_projects bp
           JOIN billing_companies bco ON bp.company_id = bco.id
           WHERE bp.active = 1"""
    ).fetchall()
    matched_projects = [p for p in projects if _word_match(p["name"])]
    logger.info("coaching/active fallback: matched projects=%r", [p["name"] for p in matched_projects])

    total_matches = len(matched_clients) + len(matched_projects)
    logger.info("coaching/active fallback: %d total matches (clients=%r projects=%r)",
                total_matches, [c["name"] for c in matched_clients], [p["name"] for p in matched_projects])

    def _resolve(candidates_clients, candidates_projects):
        """Return (type, row) or None."""
        if len(candidates_clients) + len(candidates_projects) == 1:
            if candidates_clients:
                return "client", candidates_clients[0]
            return "project", candidates_projects[0]
        return None

    resolved = _resolve(matched_clients, matched_projects)

    # Tiebreaker: when multiple word-matches exist, prefer the candidate that has
    # a banana (color_id='5') session within the last 14 days.  This disambiguates
    # cases like "Steve/Vinny" where both "Vinny Insights" and "Vinny Beranek" match
    # on "vinny" — only the one with recent banana activity is likely in progress.
    if resolved is None and total_matches > 1:
        cutoff       = now.date().isoformat()
        cutoff_start = (now - timedelta(days=14)).date().isoformat()

        matched_client_ids = [c["id"] for c in matched_clients]
        matched_project_ids = [p["id"] for p in matched_projects]

        recent_banana_clients: set[int] = set()
        recent_banana_projects: set[int] = set()

        if matched_client_ids:
            ph = ",".join("?" * len(matched_client_ids))
            rows = db.execute(
                f"SELECT client_id FROM billing_sessions WHERE client_id IN ({ph}) "
                "AND color_id='5' AND date BETWEEN ? AND ? AND is_confirmed=0",
                matched_client_ids + [cutoff_start, cutoff],
            ).fetchall()
            recent_banana_clients = {r["client_id"] for r in rows}

        if matched_project_ids:
            ph = ",".join("?" * len(matched_project_ids))
            rows = db.execute(
                f"SELECT project_id FROM billing_sessions WHERE project_id IN ({ph}) "
                "AND color_id='5' AND date BETWEEN ? AND ? AND is_confirmed=0",
                matched_project_ids + [cutoff_start, cutoff],
            ).fetchall()
            recent_banana_projects = {r["project_id"] for r in rows}

        filtered_clients  = [c for c in matched_clients  if c["id"] in recent_banana_clients]
        filtered_projects = [p for p in matched_projects if p["id"] in recent_banana_projects]
        logger.info("coaching/active tiebreaker: banana-active clients=%r projects=%r",
                    [c["name"] for c in filtered_clients], [p["name"] for p in filtered_projects])
        resolved = _resolve(filtered_clients, filtered_projects)

    if resolved is None:
        logger.info("coaching/active: still ambiguous after tiebreaker, returning inactive")
        return {"active": False}

    kind, row = resolved
    if kind == "client":
        logger.info("coaching/active: resolved to client %r", row["name"])
        return {
            "active": True,
            "type": "client",
            "client_id": row["id"],
            "project_id": None,
            "client_name": row["name"],
            "obsidian_name": row["obsidian_name"],
            "company_name": None,
        }
    logger.info("coaching/active: resolved to project %r", row["name"])
    return {
        "active": True,
        "type": "project",
        "client_id": None,
        "project_id": row["id"],
        "client_name": row["name"],
        "obsidian_name": row["obsidian_name"],
        "company_name": row["company_name"],
    }


# ---------------------------------------------------------------------------
# GET /api/coaching/clients
# ---------------------------------------------------------------------------

@router.get("/clients")
def get_coaching_clients():
    """
    Return all active clients grouped for the Coaching Clients page.
    Each company group also includes a `projects` list for active projects.

    Groups:
    - Company groups (client_type = 'company'), alphabetical by company name
    - Individual group at the bottom (client_type = 'individual'), alphabetical by first name
    """
    db = get_db()
    today = date.today()

    clients_rows = db.execute(
        """
        SELECT
            bc.id,
            bc.name,
            bc.client_type,
            bc.prepaid,
            bc.obsidian_name,
            bc.gdrive_coaching_docs_url,
            bc.manifest_gdoc_url,
            bc.status,
            bco.id   AS company_id,
            bco.name AS company_name,
            bco.default_rate
        FROM billing_clients bc
        JOIN billing_companies bco ON bc.company_id = bco.id
        WHERE bc.status IN ('active', 'infrequent')
        ORDER BY bco.name, bc.name
        """
    ).fetchall()

    client_ids = [r["id"] for r in clients_rows]
    if not client_ids:
        return {"groups": []}

    placeholders = ",".join("?" * len(client_ids))

    last_sessions = db.execute(
        f"""
        WITH sno AS (
            SELECT client_id, date, session_number,
                   ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY date) AS rn
            FROM billing_sessions
            WHERE is_confirmed = 1
              AND client_id IN ({placeholders})
        )
        SELECT client_id,
               MAX(date) AS date,
               MAX(COALESCE(session_number, rn)) AS display_session_number
        FROM sno
        GROUP BY client_id
        """,
        client_ids,
    ).fetchall()

    last_by_client = {r["client_id"]: r for r in last_sessions}

    next_sessions = db.execute(
        f"""
        WITH ranked AS (
            SELECT client_id, date,
                   ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY date ASC) AS rn
            FROM billing_sessions
            WHERE client_id IN ({placeholders})
              AND color_id = '5' AND is_confirmed = 0
        )
        SELECT client_id, date FROM ranked WHERE rn = 1
        """,
        client_ids,
    ).fetchall()

    next_by_client = {r["client_id"]: r["date"] for r in next_sessions}

    def build_client(r):
        last = last_by_client.get(r["id"])
        last_date_str = last["date"] if last else None
        display_session_number = last["display_session_number"] if last else None
        days_ago = None
        if last_date_str:
            try:
                last_date = date.fromisoformat(last_date_str)
                days_ago = (today - last_date).days
            except ValueError:
                pass
        return {
            "id": r["id"],
            "name": r["name"],
            "client_type": r["client_type"],
            "status": r["status"],
            "prepaid": bool(r["prepaid"]),
            "obsidian_name": r["obsidian_name"],
            "gdrive_coaching_docs_url": r["gdrive_coaching_docs_url"],
            "last_session_date": last_date_str,
            "display_session_number": display_session_number,
            "days_ago": days_ago,
            "next_session_date": next_by_client.get(r["id"]),
            "manifest_gdoc_url": r["manifest_gdoc_url"],
        }

    company_groups: dict[int, dict] = {}
    individual_clients: list[dict] = []

    for r in clients_rows:
        client = build_client(r)
        if r["client_type"] == "individual":
            individual_clients.append(client)
        else:
            cid = r["company_id"]
            if cid not in company_groups:
                company_groups[cid] = {
                    "company_id": cid,
                    "company_name": r["company_name"],
                    "default_rate": r["default_rate"],
                    "clients": [],
                }
            company_groups[cid]["clients"].append(client)

    # --- Fetch active projects and their session stats ---
    project_rows = db.execute(
        """SELECT bp.id, bp.name, bp.company_id, bp.billing_type, bp.obsidian_name,
                  bp.gdrive_coaching_docs_url
           FROM billing_projects bp
           WHERE bp.active = 1
           ORDER BY bp.name"""
    ).fetchall()

    project_ids = [r["id"] for r in project_rows]

    if project_ids:
        ph = ",".join("?" * len(project_ids))
        proj_last_sessions = db.execute(
            f"""WITH ranked AS (
                    SELECT project_id, date,
                           ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY date DESC) AS rn
                    FROM billing_sessions
                    WHERE project_id IN ({ph}) AND is_confirmed = 1
                )
                SELECT project_id, date FROM ranked WHERE rn = 1""",
            project_ids,
        ).fetchall()
        proj_session_counts = db.execute(
            f"""WITH sno AS (
                    SELECT project_id, session_number,
                           ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY date) AS rn
                    FROM billing_sessions
                    WHERE project_id IN ({ph}) AND is_confirmed = 1
                )
                SELECT project_id,
                       MAX(COALESCE(session_number, rn)) AS cnt
                FROM sno
                GROUP BY project_id""",
            project_ids,
        ).fetchall()
        proj_next_sessions = db.execute(
            f"""WITH ranked AS (
                    SELECT project_id, date,
                           ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY date ASC) AS rn
                    FROM billing_sessions
                    WHERE project_id IN ({ph}) AND color_id = '5' AND is_confirmed = 0
                )
                SELECT project_id, date FROM ranked WHERE rn = 1""",
            project_ids,
        ).fetchall()
    else:
        proj_last_sessions = []
        proj_session_counts = []
        proj_next_sessions = []

    proj_last_by_id = {r["project_id"]: r["date"] for r in proj_last_sessions}
    proj_count_by_id = {r["project_id"]: r["cnt"] for r in proj_session_counts}
    proj_next_by_id = {r["project_id"]: r["date"] for r in proj_next_sessions}

    def build_project(r):
        last_date_str = proj_last_by_id.get(r["id"])
        days_ago = None
        if last_date_str:
            try:
                last_date = date.fromisoformat(last_date_str)
                days_ago = (today - last_date).days
            except ValueError:
                pass
        return {
            "id": r["id"],
            "name": r["name"],
            "billing_type": r["billing_type"],
            "obsidian_name": r["obsidian_name"],
            "gdrive_coaching_docs_url": r["gdrive_coaching_docs_url"],
            "session_count": proj_count_by_id.get(r["id"], 0),
            "last_session_date": last_date_str,
            "days_ago": days_ago,
            "next_session_date": proj_next_by_id.get(r["id"]),
        }

    # Attach projects to company groups
    projects_by_company: dict[int, list[dict]] = {}
    for r in project_rows:
        projects_by_company.setdefault(r["company_id"], []).append(build_project(r))

    sorted_company_groups = sorted(company_groups.values(), key=lambda g: g["company_name"].lower())
    for g in sorted_company_groups:
        g["active_client_count"] = len(g["clients"])
        g["projects"] = projects_by_company.get(g["company_id"], [])

    individual_clients.sort(key=lambda c: c["name"].split()[0].lower())

    groups = list(sorted_company_groups)
    if individual_clients:
        groups.append({
            "company_id": None,
            "company_name": "Individual",
            "default_rate": None,
            "active_client_count": len(individual_clients),
            "clients": individual_clients,
            "projects": [],
        })

    return {"groups": groups}


# ---------------------------------------------------------------------------
# GET /api/coaching/clients/by-date
# ---------------------------------------------------------------------------

# Shared calendar_events query fragment for future/days modes
_CE_SESSION_SELECT = """
    SELECT
        ce.id              AS ce_id,
        date(ce.start_time) AS date,
        ce.start_time,
        ce.summary         AS ce_summary,
        ce.attendees_json  AS ce_attendees,
        ce.color_id,
        bs.id              AS bs_id,
        bs.client_id,
        bs.project_id,
        COALESCE(bs.is_confirmed, 0) AS is_confirmed,
        bs.obsidian_note_path,
        bc.name            AS client_name,
        bc.obsidian_name,
        bc.gdrive_coaching_docs_url,
        bc.company_id      AS bc_company_id,
        bp.name            AS project_name,
        bp.obsidian_name   AS project_obsidian_name,
        bp.gdrive_coaching_docs_url AS project_gdrive_url,
        bp.company_id      AS bp_company_id,
        bco.name           AS company_name
    FROM calendar_events ce
    LEFT JOIN billing_sessions bs  ON bs.calendar_event_id = ce.id
    LEFT JOIN billing_clients  bc  ON bc.id = bs.client_id
    LEFT JOIN billing_projects bp  ON bp.id = bs.project_id
    LEFT JOIN billing_companies bco ON bco.id = COALESCE(bc.company_id, bp.company_id)
"""


def _enrich_event_rows(raw_rows: list, db, vault_meetings=None) -> list[dict]:
    """Enrich calendar_event rows with client data and disk-based note existence.

    For rows already linked via billing_sessions, uses the JOIN data directly.
    For unlinked rows, falls back to email-primary / title-fallback matching
    (same logic as note_creator).  Sets obsidian_note_path only when the note
    actually exists on disk — so has_note = bool(obsidian_note_path) is accurate.
    """
    import json as _json
    from connectors.note_creator import (
        _build_client_lookups, _match_client_by_title,
        _MY_EMAILS, _RESOURCE_RE,
    )

    all_clients = db.execute(
        "SELECT id, name, obsidian_name, gdrive_coaching_docs_url, email, company_id "
        "FROM billing_clients WHERE status IN ('active', 'infrequent')"
    ).fetchall()
    all_companies = {
        r["id"]: r["name"]
        for r in db.execute("SELECT id, name FROM billing_companies").fetchall()
    }

    by_full, by_first = _build_client_lookups([dict(c) for c in all_clients])
    by_email = {
        c["email"].strip().lower(): dict(c)
        for c in all_clients if c["email"]
    }

    enriched: list[dict] = []
    for r in raw_rows:
        r = dict(r)

        # --- resolve client / project identity ---
        if r.get("client_id"):
            obs_name     = r.get("obsidian_name")
            gdrive_url   = r.get("gdrive_coaching_docs_url")
            client_name  = r.get("client_name") or r.get("ce_summary") or ""
            client_id    = r["client_id"]
            company_id   = r.get("bc_company_id")
            company_name = r.get("company_name") or all_companies.get(company_id, "")
        elif r.get("project_id"):
            obs_name     = r.get("project_obsidian_name")
            gdrive_url   = r.get("project_gdrive_url")
            client_name  = r.get("project_name") or r.get("ce_summary") or ""
            client_id    = None
            company_id   = r.get("bp_company_id")
            company_name = r.get("company_name") or all_companies.get(company_id, "")
        else:
            # email-primary, title-fallback
            matched = None
            ce_attendees = r.get("ce_attendees")
            if ce_attendees:
                try:
                    for a in _json.loads(ce_attendees):
                        email = (a.get("email") or "").strip().lower()
                        if not email or email in _MY_EMAILS or _RESOURCE_RE.search(email):
                            continue
                        if email in by_email:
                            matched = by_email[email]
                            break
                except Exception:
                    pass
            if not matched:
                matched = _match_client_by_title(r.get("ce_summary") or "", by_full, by_first)

            if matched:
                obs_name     = matched.get("obsidian_name") or matched.get("name")
                gdrive_url   = matched.get("gdrive_coaching_docs_url")
                client_id    = matched["id"]
                company_id   = matched.get("company_id")
                company_name = all_companies.get(company_id, "") if company_id else ""
                client_name  = matched["name"]
            else:
                obs_name = gdrive_url = client_id = company_id = None
                company_name = ""
                client_name  = r.get("ce_summary") or ""

        # --- disk-based note existence check ---
        note_path = None
        if obs_name and vault_meetings:
            try:
                fname = f"{r['date']} - {obs_name}.md"
                if (vault_meetings / fname).exists():
                    note_path = f"{_obs_folder('meetings', '8 Meetings')}/{fname}"
            except Exception:
                pass

        enriched.append({
            "id":                       r.get("bs_id") or r.get("ce_id"),
            "date":                     r["date"],
            "start_time":               r["start_time"],
            "client_id":                client_id,
            "client_name":              client_name,
            "company_name":             company_name,
            "obsidian_name":            obs_name,
            "gdrive_coaching_docs_url": gdrive_url,
            "is_confirmed":             int(r.get("is_confirmed") or 0),
            "color_id":                 r.get("color_id"),
            "obsidian_note_path":       note_path,
        })

    return enriched


@router.get("/clients/by-date")
def get_clients_by_date(mode: str = "today", days: int = 1):
    """
    Return billing sessions grouped by day for the by-date view.

    mode:
      past    — last 10 confirmed sessions (is_confirmed=1), most recent first
      today   — all sessions today (grape color_id=11 or banana color_id=5)
      next    — next 10 upcoming banana sessions (date >= today), soonest first
      week    — all sessions Mon–Sun of current week (grape + banana)
      future  — rest-of-today banana sessions if any exist after now, else tomorrow only
      (days param) — next N rolling days banana sessions (used for ;1–;9 / ;A–;Z)
    """
    db = get_db()
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
    today = datetime.now(_ET).date()
    today_str = today.isoformat()

    # Vault path for disk-based note existence checks (future/days modes)
    vault_meetings = None
    try:
        from connectors.obsidian import get_vault_path
        _vault = get_vault_path()
        if _vault:
            vault_meetings = _vault / _obs_folder("meetings", "8 Meetings")
    except Exception:
        pass

    # Monday of current week (ET-based)
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    if mode == "past":
        rows = db.execute(
            """
            SELECT
                bs.id, bs.date, bs.client_id, bs.company_id,
                bs.is_confirmed, bs.color_id, bs.obsidian_note_path,
                bs.session_number, bs.project_id,
                bc.name   AS client_name,
                bc.obsidian_name,
                bc.gdrive_coaching_docs_url,
                bco.name  AS company_name,
                ce.start_time
            FROM billing_sessions bs
            JOIN billing_clients bc ON bc.id = bs.client_id
            JOIN billing_companies bco ON bco.id = bs.company_id
            LEFT JOIN calendar_events ce ON ce.id = bs.calendar_event_id
            WHERE bs.is_confirmed = 1
              AND bs.client_id IS NOT NULL
              AND COALESCE(bs.canceled, 0) = 0
            ORDER BY bs.date DESC, ce.start_time ASC
            LIMIT 10
            """
        ).fetchall()

    elif mode == "today":
        rows = db.execute(
            """
            SELECT
                bs.id, bs.date, bs.client_id, bs.company_id,
                bs.is_confirmed, bs.color_id, bs.obsidian_note_path,
                bs.session_number, bs.project_id,
                bc.name   AS client_name,
                bc.obsidian_name,
                bc.gdrive_coaching_docs_url,
                bco.name  AS company_name,
                ce.start_time
            FROM billing_sessions bs
            JOIN billing_clients bc ON bc.id = bs.client_id
            JOIN billing_companies bco ON bco.id = bs.company_id
            LEFT JOIN calendar_events ce ON ce.id = bs.calendar_event_id
            WHERE bs.date = ?
              AND bs.client_id IS NOT NULL
              AND bs.color_id IN ('5', '11')
              AND COALESCE(bs.canceled, 0) = 0
            ORDER BY ce.start_time ASC
            """,
            [today_str],
        ).fetchall()

    elif mode == "next":
        # Query calendar_events directly (like future/days) so events not yet in
        # billing_sessions still appear. Banana (color_id=5) only, date >= today.
        raw_rows = db.execute(
            _CE_SESSION_SELECT +
            "WHERE ce.color_id = '5' "
            "AND date(ce.start_time) >= ? "
            "AND COALESCE(bs.canceled, 0) = 0 "
            "ORDER BY ce.start_time ASC "
            "LIMIT 10",
            [today_str],
        ).fetchall()
        rows = _enrich_event_rows(raw_rows, db, vault_meetings)

    elif mode == "week":
        # Query calendar_events directly so events not yet in billing_sessions appear.
        raw_rows = db.execute(
            _CE_SESSION_SELECT +
            "WHERE ce.color_id IN ('3', '5') "
            "AND date(ce.start_time) BETWEEN ? AND ? "
            "AND COALESCE(bs.canceled, 0) = 0 "
            "ORDER BY ce.start_time ASC",
            [week_start.isoformat(), week_end.isoformat()],
        ).fetchall()
        rows = _enrich_event_rows(raw_rows, db, vault_meetings)

    elif mode == "future":
        # Show grape/banana events remaining today if any exist after now; else tomorrow only.
        now_str = datetime.now(_ET).isoformat()
        today_remaining = db.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM calendar_events ce
            WHERE date(ce.start_time) = ?
              AND ce.color_id IN ('3', '5')
              AND ce.start_time > ?
            """,
            [today_str, now_str],
        ).fetchone()["cnt"]

        if today_remaining > 0:
            future_submode = "today"
            target_date = today_str
        else:
            future_submode = "tomorrow"
            target_date = (today + timedelta(days=1)).isoformat()

        raw_rows = db.execute(
            _CE_SESSION_SELECT +
            "WHERE ce.color_id IN ('3', '5') AND date(ce.start_time) = ? "
            "AND COALESCE(bs.canceled, 0) = 0 "
            "ORDER BY ce.start_time ASC",
            [target_date],
        ).fetchall()
        rows = _enrich_event_rows(raw_rows, db, vault_meetings)

    else:
        # ;N days mode (days param)
        end_date = today + timedelta(days=days)
        raw_rows = db.execute(
            _CE_SESSION_SELECT +
            "WHERE ce.color_id IN ('3', '5') "
            "AND date(ce.start_time) BETWEEN ? AND ? "
            "AND COALESCE(bs.canceled, 0) = 0 "
            "ORDER BY ce.start_time ASC",
            [today_str, end_date.isoformat()],
        ).fetchall()
        rows = _enrich_event_rows(raw_rows, db, vault_meetings)

    # Build per-session display_session_number from confirmed counts
    client_ids = list({r["client_id"] for r in rows if r["client_id"]})
    session_numbers: dict[int, int] = {}
    if client_ids:
        ph = ",".join("?" * len(client_ids))
        sn_rows = db.execute(
            f"""
            WITH sno AS (
                SELECT id, client_id, date, session_number,
                       ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY date) AS rn
                FROM billing_sessions
                WHERE is_confirmed = 1
            ),
            ranked AS (
                SELECT sno.client_id,
                       COALESCE(sno.session_number, sno.rn) AS display_session_number,
                       ROW_NUMBER() OVER (PARTITION BY sno.client_id ORDER BY sno.date DESC) AS recency
                FROM sno
                WHERE sno.client_id IN ({ph})
            )
            SELECT client_id, display_session_number
            FROM ranked WHERE recency = 1
            """,
            client_ids,
        ).fetchall()
        session_numbers = {r["client_id"]: r["display_session_number"] for r in sn_rows}

    # Group sessions by day
    from collections import defaultdict
    days_map: dict[str, list] = defaultdict(list)

    for r in rows:
        day_key = r["date"]
        start_time = r["start_time"]  # ISO string or None

        # Format time as "2:00pm"
        time_str = None
        if start_time:
            try:
                dt = datetime.fromisoformat(start_time)
                h, m = dt.hour, dt.minute
                ampm = "am" if h < 12 else "pm"
                h12 = h % 12 or 12
                time_str = f"{h12}:{m:02d}{ampm}" if m else f"{h12}{ampm}"
            except ValueError:
                pass

        # Days relative to today
        try:
            session_date = date.fromisoformat(r["date"])
            delta = (session_date - today).days
            if delta == 0:
                relative = "today"
            elif delta < 0:
                relative = f"{abs(delta)}d ago"
            else:
                relative = f"in {delta}d"
        except ValueError:
            relative = None

        # Obsidian note exists check (path is set)
        has_note = bool(r["obsidian_note_path"])

        days_map[day_key].append({
            "id": r["id"],
            "date": r["date"],
            "time": time_str,
            "client_id": r["client_id"],
            "client_name": r["client_name"],
            "company_name": r["company_name"],
            "obsidian_name": r["obsidian_name"],
            "gdrive_coaching_docs_url": r["gdrive_coaching_docs_url"],
            "is_confirmed": bool(r["is_confirmed"]),
            "color_id": r["color_id"],
            "display_session_number": session_numbers.get(r["client_id"]),
            "relative": relative,
            "has_note": has_note,
            "obsidian_note_path": r["obsidian_note_path"],
        })

    # Format day group headers
    day_groups = []
    for day_key in sorted(days_map.keys(), reverse=(mode == "past")):
        sessions = days_map[day_key]
        try:
            d = date.fromisoformat(day_key)
            dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d.weekday()]
            mon = d.strftime("%b")
            header = f"{dow} {mon} {d.day}"
        except ValueError:
            header = day_key
        day_groups.append({
            "date": day_key,
            "header": header,
            "session_count": len(sessions),
            "sessions": sessions,
        })

    result: dict = {"mode": mode, "day_groups": day_groups}
    if mode == "future":
        result["future_submode"] = future_submode
    return result


# ---------------------------------------------------------------------------
# POST /api/coaching/sessions/detect-cancellations
# ---------------------------------------------------------------------------

@router.post("/sessions/detect-cancellations")
def detect_cancellations(dry_run: bool = False):
    """Scan billing_sessions from the last 7 days for cancelled calendar events.

    For each session whose calendar event is cancelled or missing:
    - Sets billing_sessions.canceled = 1
    - Renames the Obsidian note to append ' - CANCELED' before the .md extension

    dry_run=True reports what would change without writing anything.
    """
    db = get_db() if dry_run else None

    seven_days_ago = (datetime.now().date() - timedelta(days=7)).isoformat()

    with get_write_db() as write_db:
        read_db = write_db  # same connection for reads + writes

        rows = read_db.execute(
            """
            SELECT bs.id, bs.date, bs.calendar_event_id, bs.obsidian_note_path,
                   ce.status AS event_status
            FROM billing_sessions bs
            LEFT JOIN calendar_events ce ON ce.id = bs.calendar_event_id
            WHERE bs.date >= ?
              AND COALESCE(bs.canceled, 0) = 0
              AND bs.calendar_event_id IS NOT NULL
            ORDER BY bs.date DESC
            """,
            (seven_days_ago,),
        ).fetchall()

    canceled_ids: list[int] = []
    renamed: list[dict] = []
    not_found: list[dict] = []
    errors: list[str] = []

    # Vault path for note renaming
    vault_root = None
    try:
        from connectors.obsidian import get_vault_path
        vault_root = get_vault_path()
    except Exception:
        pass

    for r in rows:
        event_status = r["event_status"]  # None if LEFT JOIN found nothing
        calendar_event_id = r["calendar_event_id"]

        # Detect: cancelled status OR event_id present but no matching row in calendar_events
        is_cancelled = (event_status == "cancelled") or (event_status is None)

        if not is_cancelled:
            continue

        session_id = r["id"]
        note_path = r["obsidian_note_path"]  # e.g. "8 Meetings/2026-04-23 - Katie Rae.md"

        canceled_ids.append(session_id)

        # Rename Obsidian note
        new_note_path = None
        if note_path and vault_root:
            old_file = vault_root / note_path
            if old_file.exists():
                stem = old_file.stem
                if not stem.endswith(" - CANCELED"):
                    new_name = f"{stem} - CANCELED.md"
                    new_file = old_file.parent / new_name
                    new_note_path = str(new_file.relative_to(vault_root))
                    if not dry_run:
                        try:
                            old_file.rename(new_file)
                            renamed.append({"id": session_id, "old": note_path, "new": new_note_path})
                        except Exception as e:
                            errors.append(f"Session {session_id}: rename failed — {e}")
                            new_note_path = None
                    else:
                        renamed.append({"id": session_id, "old": note_path, "new": new_note_path})
            else:
                not_found.append({"id": session_id, "path": note_path})

        if not dry_run and canceled_ids:
            # Write in the same loop iteration to keep rename + DB update consistent
            with get_write_db() as wdb:
                wdb.execute(
                    "UPDATE billing_sessions SET canceled = 1, obsidian_note_path = ? WHERE id = ?",
                    (new_note_path or note_path, session_id),
                )

    if not dry_run and not canceled_ids:
        pass  # nothing to do

    return {
        "dry_run": dry_run,
        "canceled_count": len(canceled_ids),
        "renamed": renamed,
        "note_not_found": not_found,
        "errors": errors,
        "session_ids": canceled_ids,
    }


# ---------------------------------------------------------------------------
# GET /api/coaching/vinny-status
# ---------------------------------------------------------------------------

@router.get("/vinny-status")
def vinny_status():
    """Check whether the Vinny Chat frontend (Vite dev server) is running at localhost:5174."""
    try:
        resp = httpx.get("http://localhost:5174/", timeout=1.5, follow_redirects=True)
        running = resp.status_code == 200 and "html" in resp.headers.get("content-type", "")
    except Exception:
        running = False
    return {"running": running}


# ---------------------------------------------------------------------------
# POST /api/coaching/wordcloud
# ---------------------------------------------------------------------------

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"\*([^*]+)\*")
_URL_RE = re.compile(r"https?://\S+")
_TOKEN_RE = re.compile(r"[a-zA-Z']+")

_SKIP_SECTIONS_NEW = {"history", "granola notes", "granola summary", "meetings"}
_TARGET_SECTIONS_NEW = {"notes", "coaching insights", "action items"}
_SKIP_BULLET_LABELS = {"granola summary", "meetings", "granola notes"}


def _extract_note_text(content: str) -> str:
    """Extract coaching-relevant text from an Obsidian session note (both old and new formats)."""
    lines = content.split("\n")

    # Strip YAML frontmatter
    i = 0
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            i += 1
        i += 1  # skip closing ---

    body = lines[i:]
    has_section_headers = any(ln.startswith("## ") for ln in body)
    result: list[str] = []

    if has_section_headers:
        # New-format notes: only include content under target ## sections
        in_target = False
        in_code = False
        for ln in body:
            stripped = ln.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            if ln.startswith("## "):
                section = ln[3:].strip().lower()
                in_target = section in _TARGET_SECTIONS_NEW
                continue
            if in_target:
                result.append(ln)
    else:
        # Old-format notes: bullet-list structure; skip Granola Summary / Meetings sections
        in_skip = False
        in_code = False
        for ln in body:
            stripped = ln.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            # Bold-bullet section headers: "- **Label**"
            m = re.match(r"^\s*-\s+\*\*(.+?)\*\*\s*$", ln)
            if m:
                label = m.group(1).strip().lower()
                if label in _SKIP_BULLET_LABELS:
                    in_skip = True
                    continue
                elif label == "notes":
                    in_skip = False
                    continue  # skip the header line itself
                else:
                    in_skip = False
            # Plain "- Notes" (no bold)
            if re.match(r"^\s*-\s+Notes\s*$", ln):
                in_skip = False
                continue
            # ### headings inside old-format notes are inside Granola sections
            if ln.startswith("#"):
                continue
            # Pure wikilink reference lines
            if re.match(r"^\s*-?\s*\[\[.*?\]\]\s*$", ln):
                continue
            if in_skip:
                continue
            result.append(ln)

    text = "\n".join(result)
    # Resolve wikilinks → display text
    text = _WIKILINK_RE.sub(lambda m: m.group(2) or m.group(1), text)
    text = _BOLD_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    text = _URL_RE.sub("", text)
    return text


def _tokenize(text: str) -> list[str]:
    """Lowercase tokens, min length 3, strip surrounding apostrophes."""
    return [
        w.strip("'")
        for w in _TOKEN_RE.findall(text.lower())
        if len(w.strip("'")) >= 3
    ]


def _load_wordcloud_config() -> tuple[set[str], int, int]:
    """Load stopwords and display settings from wordcloud.json. Returns (stopwords, min_freq, max_words)."""
    config_path = Path(__file__).parent.parent / "wordcloud.json"
    stopwords: set[str] = set()
    min_frequency = 2
    max_words = 100
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
            for lst in cfg.get("stopwords", {}).values():
                if isinstance(lst, list):
                    stopwords.update(w.lower() for w in lst)
            display = cfg.get("display", {})
            min_frequency = int(display.get("min_frequency", 2))
            max_words = int(display.get("max_words", 100))
        except Exception:
            pass
    return stopwords, min_frequency, max_words


class WordCloudRequest(BaseModel):
    client_ids: list[int]
    project_ids: list[int] = []
    session_count: int = 10
    recency_weight: float = 0.0


@router.post("/wordcloud")
def get_wordcloud(body: WordCloudRequest):
    """
    Generate word cloud data from session notes for the given clients.

    Reads vault notes, extracts text from Notes / Coaching Insights / Action Items,
    applies stop words, applies recency weighting, returns word frequencies with
    per-word session lists.
    """
    from connectors.obsidian import get_vault_path

    session_count = max(3, min(50, body.session_count))
    recency_weight = max(0.0, min(5.0, body.recency_weight))

    vault = get_vault_path()
    if not vault:
        raise HTTPException(status_code=500, detail="Obsidian vault not configured")
    meetings_dir = vault / _obs_folder("meetings", "8 Meetings")

    stopwords, min_frequency, max_words = _load_wordcloud_config()

    db = get_db()

    word_freq: dict[str, float] = {}
    # session list per word: deduplicated by (date, client_name)
    word_sessions: dict[str, list[dict]] = {}

    clients_analyzed: list[str] = []
    sessions_analyzed = 0

    for client_id in body.client_ids:
        row = db.execute(
            "SELECT name, obsidian_name FROM billing_clients WHERE id = ?",
            (client_id,),
        ).fetchone()
        if not row:
            continue

        client_name = row["name"]
        obsidian_name = row["obsidian_name"] or client_name
        clients_analyzed.append(client_name)

        sessions = db.execute(
            """SELECT date FROM billing_sessions
               WHERE client_id = ? AND is_confirmed = 1
               ORDER BY date DESC LIMIT ?""",
            (client_id, session_count),
        ).fetchall()

        n = len(sessions)
        for rank, sess in enumerate(sessions):
            date_str = sess["date"]
            fpath = meetings_dir / f"{date_str} - {obsidian_name}.md"
            if not fpath.exists():
                continue

            sessions_analyzed += 1
            try:
                content = fpath.read_text(encoding="utf-8")
            except OSError:
                continue

            text = _extract_note_text(content)
            tokens = _tokenize(text)

            # Recency weight: rank 0 (most recent) → 1 + weight; rank n-1 → 1.0
            if recency_weight > 0 and n > 1:
                w = 1.0 + recency_weight * (1.0 - rank / (n - 1))
            else:
                w = 1.0

            seen_in_session: set[str] = set()
            for token in tokens:
                if token in stopwords or len(token) < 3:
                    continue
                word_freq[token] = word_freq.get(token, 0.0) + w
                if token not in seen_in_session:
                    seen_in_session.add(token)
                    if token not in word_sessions:
                        word_sessions[token] = []
                    # Deduplicate session entries
                    if not any(
                        s["date"] == date_str and s["client_name"] == client_name
                        for s in word_sessions[token]
                    ):
                        word_sessions[token].append({
                            "date": date_str,
                            "client_name": client_name,
                            "obsidian_name": obsidian_name,
                            "path": f"{_obs_folder('meetings', '8 Meetings')}/{date_str} - {obsidian_name}.md",
                        })

    # --- Project sessions ---
    for project_id in body.project_ids:
        row = db.execute(
            "SELECT name, obsidian_name FROM billing_projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if not row:
            continue

        project_name = row["name"]
        obsidian_name = row["obsidian_name"] or project_name
        clients_analyzed.append(project_name)

        sessions = db.execute(
            """SELECT date FROM billing_sessions
               WHERE project_id = ? AND is_confirmed = 1
               ORDER BY date DESC LIMIT ?""",
            (project_id, session_count),
        ).fetchall()

        n = len(sessions)
        for rank, sess in enumerate(sessions):
            date_str = sess["date"]
            fpath = meetings_dir / f"{date_str} - {obsidian_name}.md"
            if not fpath.exists():
                continue

            sessions_analyzed += 1
            try:
                content = fpath.read_text(encoding="utf-8")
            except OSError:
                continue

            text = _extract_note_text(content)
            tokens = _tokenize(text)

            if recency_weight > 0 and n > 1:
                w = 1.0 + recency_weight * (1.0 - rank / (n - 1))
            else:
                w = 1.0

            seen_in_session: set[str] = set()
            for token in tokens:
                if token in stopwords or len(token) < 3:
                    continue
                word_freq[token] = word_freq.get(token, 0.0) + w
                if token not in seen_in_session:
                    seen_in_session.add(token)
                    if token not in word_sessions:
                        word_sessions[token] = []
                    if not any(
                        s["date"] == date_str and s["client_name"] == project_name
                        for s in word_sessions[token]
                    ):
                        word_sessions[token].append({
                            "date": date_str,
                            "client_name": project_name,
                            "obsidian_name": obsidian_name,
                            "path": f"{_obs_folder('meetings', '8 Meetings')}/{date_str} - {obsidian_name}.md",
                        })

    # Filter, sort, cap
    result_words = []
    for word, freq in word_freq.items():
        if freq < min_frequency:
            continue
        sessions_list = sorted(
            word_sessions.get(word, []),
            key=lambda s: s["date"],
            reverse=True,
        )
        result_words.append({
            "text": word,
            "value": round(freq, 2),
            "sessions": sessions_list,
        })

    result_words.sort(key=lambda x: x["value"], reverse=True)
    result_words = result_words[:max_words]

    return {
        "words": result_words,
        "sessions_analyzed": sessions_analyzed,
        "clients": clients_analyzed,
    }


# ---------------------------------------------------------------------------
# Granola Notes Sync  (POST /coaching/granola/sync, GET /coaching/granola/status)
# ---------------------------------------------------------------------------

_granola_sync_lock = threading.Lock()
_granola_sync_running = False
_granola_last_result: dict | None = None
_granola_last_run: str | None = None
_granola_last_error: str | None = None


def _persist_sync_state(source: str, status: str, error: str | None, items: int):
    """Write a sync_state row so results survive server restarts."""
    try:
        with get_write_db() as db:
            db.execute(
                """INSERT INTO sync_state (source, last_sync_at, last_sync_status, last_error, items_synced)
                   VALUES (?, datetime('now'), ?, ?, ?)
                   ON CONFLICT(source) DO UPDATE SET
                     last_sync_at=excluded.last_sync_at,
                     last_sync_status=excluded.last_sync_status,
                     last_error=excluded.last_error,
                     items_synced=excluded.items_synced""",
                (source, status, error, items),
            )
            db.commit()
    except Exception as exc:
        logger.warning("Could not persist sync_state for %s: %s", source, exc)


@router.post("/granola/sync")
def trigger_granola_sync(days_back: int = 7, force: bool = False, dry_run: bool = False):
    """Trigger a Granola notes sync. Runs synchronously (blocking).

    force=True appends to notes that already have Granola content (with a datestamp header).
    dry_run=True fetches and matches but writes nothing; returns a per-note report.
    Always returns JSON (never raises 500) so the UI can display errors.
    """
    global _granola_sync_running, _granola_last_result, _granola_last_run, _granola_last_error

    # Dry runs skip the mutex and state updates — they're read-only
    if dry_run:
        try:
            from connectors.granola_notes import sync_granola_notes
            logger.info("Starting Granola dry run: days_back=%d force=%s", days_back, force)
            result = sync_granola_notes(days_back=days_back, force=force, dry_run=True)
            return {"status": "ok", "result": result}
        except Exception as e:
            err = str(e)
            logger.error("Granola dry run failed: %s", err)
            return {"status": "error", "error": err, "result": None}

    with _granola_sync_lock:
        if _granola_sync_running:
            raise HTTPException(status_code=409, detail="Granola sync already in progress")
        _granola_sync_running = True

    try:
        from connectors.granola_notes import sync_granola_notes

        logger.info("Starting Granola sync: days_back=%d force=%s", days_back, force)
        result = sync_granola_notes(days_back=days_back, force=force)
        logger.info("Granola sync finished: %s", result)
        now = datetime.now().isoformat()
        with _granola_sync_lock:
            _granola_last_result = result
            _granola_last_run = now
            _granola_last_error = None
        _persist_sync_state("granola_notes", "success", None, result.get("written", 0))
        return {"status": "ok", "result": result}
    except Exception as e:
        err = str(e)
        tb = traceback.format_exc()
        logger.error("Granola sync failed: %s\n%s", err, tb)
        now = datetime.now().isoformat()
        with _granola_sync_lock:
            _granola_last_error = err
            _granola_last_run = now
        _persist_sync_state("granola_notes", "error", err, 0)
        # Return error as JSON body (not HTTPException) so the UI can display it
        return {"status": "error", "error": err, "result": None}
    finally:
        with _granola_sync_lock:
            _granola_sync_running = False


@router.get("/granola/status")
def granola_sync_status():
    """Return last Granola sync run info."""
    return {
        "running": _granola_sync_running,
        "last_run": _granola_last_run,
        "last_result": _granola_last_result,
        "last_error": _granola_last_error,
    }


# ---------------------------------------------------------------------------
# Note Creation  (POST /coaching/notes/create, GET /coaching/notes/status,
#                 PATCH /coaching/notes/config)
# ---------------------------------------------------------------------------

_notes_lock = threading.Lock()
_notes_running = False
_notes_last_result: dict | None = None
_notes_last_run: str | None = None
_notes_last_error: str | None = None


@router.post("/notes/create")
def trigger_note_creation(dry_run: bool = False):
    """Trigger daily & meeting note creation for the configured days_ahead window.

    dry_run=True computes what would be created/updated without writing any files.
    """
    global _notes_running, _notes_last_result, _notes_last_run, _notes_last_error

    # Dry runs skip the mutex and state updates
    if dry_run:
        try:
            from app_config import get_note_creation_config
            from connectors.note_creator import create_upcoming_notes

            cfg = get_note_creation_config()
            days_ahead = int(cfg.get("days_ahead", 5))
            result = create_upcoming_notes(days_ahead=days_ahead, dry_run=True)
            return {"status": "ok", "result": result}
        except Exception as e:
            return {"status": "error", "error": str(e), "result": None}

    with _notes_lock:
        if _notes_running:
            raise HTTPException(status_code=409, detail="Note creation already in progress")
        _notes_running = True

    try:
        from app_config import get_note_creation_config
        from connectors.note_creator import create_upcoming_notes

        cfg = get_note_creation_config()
        days_ahead = int(cfg.get("days_ahead", 5))
        result = create_upcoming_notes(days_ahead=days_ahead)
        with _notes_lock:
            _notes_last_result = result
            _notes_last_run = datetime.now().isoformat()
            _notes_last_error = None
        return {"status": "ok", "result": result}
    except Exception as e:
        with _notes_lock:
            _notes_last_error = str(e)
            _notes_last_run = datetime.now().isoformat()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        with _notes_lock:
            _notes_running = False


@router.get("/notes/status")
def note_creation_status():
    """Return last note creation run info plus current config."""
    from app_config import get_note_creation_config

    cfg = get_note_creation_config()
    return {
        "running": _notes_running,
        "last_run": _notes_last_run,
        "last_result": _notes_last_result,
        "last_error": _notes_last_error,
        "config": cfg,
    }


class NoteCreationConfigUpdate(BaseModel):
    days_ahead: int


@router.patch("/notes/config")
def update_note_creation_config_endpoint(body: NoteCreationConfigUpdate):
    """Update note creation configuration."""
    from app_config import update_note_creation_config

    if body.days_ahead < 1 or body.days_ahead > 30:
        raise HTTPException(status_code=400, detail="days_ahead must be between 1 and 30")
    cfg = update_note_creation_config({"days_ahead": body.days_ahead})
    return {"status": "ok", "config": cfg}


# ---------------------------------------------------------------------------
# GET /api/coaching/setup/companies
# ---------------------------------------------------------------------------

@router.get("/setup/companies")
def setup_list_companies():
    """Return all active companies for the Setup page dropdowns.

    Each entry includes gdrive_folder_url so the frontend can filter
    to only those ready for client/project creation.
    """
    db = get_db()
    rows = db.execute(
        """SELECT id, name, abbrev, default_rate, gdrive_folder_url
           FROM billing_companies
           WHERE active = 1
           ORDER BY name""",
    ).fetchall()
    return {"companies": [dict(r) for r in rows]}


@router.get("/setup/clients")
def setup_list_clients():
    """Return all active/infrequent clients with company name and session count."""
    db = get_db()
    rows = db.execute(
        """SELECT bc.id, bc.name, bc.status, bc.email,
                  bc.gdrive_coaching_docs_url,
                  bco.name AS company_name,
                  (SELECT COUNT(*) FROM billing_sessions bs WHERE bs.client_id = bc.id) AS session_count
           FROM billing_clients bc
           JOIN billing_companies bco ON bc.company_id = bco.id
           WHERE bc.status IN ('active', 'infrequent')
           ORDER BY bco.name, bc.name""",
    ).fetchall()
    return {"clients": [dict(r) for r in rows]}


@router.get("/setup/projects")
def setup_list_projects():
    """Return all active projects with company name and session count."""
    db = get_db()
    rows = db.execute(
        """SELECT bp.id, bp.name, bp.billing_type, bp.gdrive_folder_url,
                  bco.name AS company_name,
                  (SELECT COUNT(*) FROM billing_sessions bs WHERE bs.project_id = bp.id) AS session_count
           FROM billing_projects bp
           JOIN billing_companies bco ON bp.company_id = bco.id
           WHERE bp.active = 1
           ORDER BY bco.name, bp.name""",
    ).fetchall()
    return {"projects": [dict(r) for r in rows]}


def _seed_remove(key: str, name: str) -> None:
    """Remove all entries matching name from billing_seed.json[key] (non-fatal)."""
    try:
        import json as _json
        seed_path = Path(__file__).resolve().parent.parent / "dashy_billing_seed.json"
        if not seed_path.exists():
            return
        seed_data = _json.loads(seed_path.read_text(encoding="utf-8"))
        before = len(seed_data.get(key, []))
        seed_data[key] = [e for e in seed_data.get(key, []) if e.get("name") != name]
        removed = before - len(seed_data[key])
        seed_path.write_text(_json.dumps(seed_data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Removed %d entry(s) named %r from billing_seed.json[%s]", removed, name, key)
    except Exception as exc:
        logger.warning("billing_seed.json removal failed for %r in %r: %s", name, key, exc)


@router.delete("/setup/company/{company_id}")
def setup_delete_company(company_id: int):
    from urllib.parse import quote
    db_r = get_db()
    company = db_r.execute(
        "SELECT id, name, gdrive_folder_url FROM billing_companies WHERE id = ?", (company_id,)
    ).fetchone()
    if not company:
        db_r.close()
        raise HTTPException(status_code=404, detail="Company not found")
    name = company["name"]
    gdrive_url = company["gdrive_folder_url"] or ""
    obsidian_url = (
        f"obsidian://open?vault=MyNotes&file=1%20Company%2F"
        f"{quote(name, safe='')}%2F{quote(name, safe='')}.md"
    )

    active_clients = db_r.execute(
        """SELECT name FROM billing_clients
           WHERE company_id = ? AND status IN ('active', 'infrequent')
           ORDER BY name""",
        (company_id,),
    ).fetchall()
    active_projects = db_r.execute(
        "SELECT name FROM billing_projects WHERE company_id = ? AND active = 1",
        (company_id,),
    ).fetchall()
    db_r.close()

    if active_clients:
        client_names = ", ".join(r["name"] for r in active_clients)
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete — {len(active_clients)} active client(s): {client_names}. Delete them first.",
        )
    if active_projects:
        project_names = ", ".join(r["name"] for r in active_projects)
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete — {len(active_projects)} active project(s): {project_names}. Delete them first.",
        )

    with get_write_db() as db:
        db.execute("DELETE FROM billing_companies WHERE id = ?", (company_id,))
        db.commit()

    _seed_remove("companies", name)
    logger.info("Deleted company %r (id=%d)", name, company_id)
    return {"deleted": True, "name": name, "gdrive_url": gdrive_url, "obsidian_url": obsidian_url}


@router.delete("/setup/client/{client_id}")
def setup_delete_client(client_id: int):
    from urllib.parse import quote
    db_r = get_db()
    client = db_r.execute(
        """SELECT bc.id, bc.name, bc.obsidian_name, bc.gdrive_coaching_docs_url,
                  bco.name AS company_name
           FROM billing_clients bc
           JOIN billing_companies bco ON bc.company_id = bco.id
           WHERE bc.id = ?""",
        (client_id,),
    ).fetchone()
    if not client:
        db_r.close()
        raise HTTPException(status_code=404, detail="Client not found")
    name = client["name"]
    company_name = client["company_name"]
    obsidian_name = client["obsidian_name"] or name
    gdrive_url = client["gdrive_coaching_docs_url"] or ""
    obsidian_url = f"obsidian://open?vault=MyNotes&file=1%20People%2F{quote(obsidian_name, safe='')}.md"

    # Block if sessions are on open (non-draft, non-paid) invoices
    invoiced = db_r.execute(
        """SELECT COUNT(*) AS cnt
           FROM billing_sessions bs
           JOIN billing_invoice_lines bil ON bs.invoice_line_id = bil.id
           JOIN billing_invoices bi ON bil.invoice_id = bi.id
           WHERE bs.client_id = ? AND bi.status NOT IN ('draft', 'paid')""",
        (client_id,),
    ).fetchone()
    db_r.close()

    if invoiced and invoiced["cnt"] > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete — {invoiced['cnt']} session(s) are on unpaid invoices. Resolve invoices first.",
        )

    with get_write_db() as db:
        db.execute("DELETE FROM billing_sessions WHERE client_id = ?", (client_id,))
        db.execute("DELETE FROM billing_prepaid_blocks WHERE client_id = ?", (client_id,))
        db.execute("DELETE FROM billing_clients WHERE id = ?", (client_id,))
        db.commit()

    _seed_remove("clients", name)
    logger.info("Deleted client %r (id=%d, company=%r)", name, client_id, company_name)
    return {"deleted": True, "name": name, "company_name": company_name, "gdrive_url": gdrive_url, "obsidian_url": obsidian_url}


@router.delete("/setup/project/{project_id}")
def setup_delete_project(project_id: int):
    from urllib.parse import quote
    db_r = get_db()
    project = db_r.execute(
        """SELECT bp.id, bp.name, bp.obsidian_name, bp.gdrive_folder_url,
                  bco.name AS company_name
           FROM billing_projects bp
           JOIN billing_companies bco ON bp.company_id = bco.id
           WHERE bp.id = ?""",
        (project_id,),
    ).fetchone()
    if not project:
        db_r.close()
        raise HTTPException(status_code=404, detail="Project not found")
    name = project["name"]
    company_name = project["company_name"]
    obsidian_name = project["obsidian_name"] or name
    gdrive_url = project["gdrive_folder_url"] or ""
    obsidian_url = (
        f"obsidian://open?vault=MyNotes&file=1%20Company%2F"
        f"{quote(company_name, safe='')}%2F{quote(obsidian_name, safe='')}.md"
    )

    invoiced = db_r.execute(
        """SELECT COUNT(*) AS cnt
           FROM billing_sessions bs
           JOIN billing_invoice_lines bil ON bs.invoice_line_id = bil.id
           JOIN billing_invoices bi ON bil.invoice_id = bi.id
           WHERE bs.project_id = ? AND bi.status NOT IN ('draft', 'paid')""",
        (project_id,),
    ).fetchone()
    db_r.close()

    if invoiced and invoiced["cnt"] > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete — {invoiced['cnt']} session(s) are on unpaid invoices. Resolve invoices first.",
        )

    with get_write_db() as db:
        db.execute("DELETE FROM billing_sessions WHERE project_id = ?", (project_id,))
        db.execute("DELETE FROM billing_projects WHERE id = ?", (project_id,))
        db.commit()

    _seed_remove("projects", name)
    logger.info("Deleted project %r (id=%d, company=%r)", name, project_id, company_name)
    return {"deleted": True, "name": name, "company_name": company_name, "gdrive_url": gdrive_url, "obsidian_url": obsidian_url}


# ---------------------------------------------------------------------------
# Setup — shared constants and helpers
# ---------------------------------------------------------------------------

def _drive_root_folder_id() -> str:
    from app_config import get_install_config
    return get_install_config().get("google_drive", {}).get("root_coaching_folder_id", "1Y6zVoKjaCOSs2PJTPSwAELUUBOv7PBy3")


def _drive_template_folder_id() -> str:
    from app_config import get_install_config
    return get_install_config().get("google_drive", {}).get("template_folder_id", "1ejHI_5Y6lghWVL22ztV1O3YMRxxQeiHo")


def _obs_folder(key: str, default: str) -> str:
    from app_config import get_install_config
    return get_install_config().get("obsidian", {}).get("folders", {}).get(key, default)


def _drive_subfolder(key: str, default: str) -> str:
    from app_config import get_install_config
    return get_install_config().get("google_drive", {}).get("subfolder_names", {}).get(key, default)


def _folder_id_from_url(url: str) -> str | None:
    """Extract Google Drive folder ID from a folders URL.

    Handles: https://drive.google.com/drive/folders/{id}
             https://drive.google.com/drive/folders/{id}?usp=sharing
    """
    if not url:
        return None
    try:
        part = url.split("/folders/")[-1]
        return part.split("?")[0].strip()
    except Exception:
        return None


def _obsidian_company_page(vault: Path, company_name: str) -> dict:
    """Ensure 1 Company/{company_name}/{company_name}.md exists.

    - Creates the folder if absent.
    - Moves a flat 1 Company/{company_name}.md into the folder if present.
    - Creates a minimal frontmatter page if neither exists.

    Returns {"action": "moved"|"created"|"exists", "path": str}.
    """
    folder = vault / _obs_folder("companies", "1 Company") / company_name
    page = folder / f"{company_name}.md"
    flat = vault / _obs_folder("companies", "1 Company") / f"{company_name}.md"

    folder.mkdir(parents=True, exist_ok=True)

    if page.exists():
        return {"action": "exists", "path": str(page)}

    if flat.exists():
        flat.rename(page)
        return {"action": "moved", "path": str(page)}

    page.write_text(
        f"---\ntype: company\nstatus: active\ntags:\n  - company\n---\n\n# {company_name}\n",
        encoding="utf-8",
    )
    return {"action": "created", "path": str(page)}


def _obsidian_client_page(
    vault: Path,
    client_name: str,
    company_name: str,
    coaching_agreement_url: str,
    wheel_of_life_url: str,
    manifest_gdoc_url: str = "",
) -> Path:
    """Write 1 People/{client_name}.md from the client page template (spec §6.1)."""
    page = vault / _obs_folder("clients", "1 People") / f"{client_name}.md"
    if page.exists():
        return page

    agreement_line = (
        f"    - [Coaching agreement]({coaching_agreement_url})"
        if coaching_agreement_url
        else "    - Coaching agreement: "
    )
    wol_line = (
        f"    - [Wheel of Life]({wheel_of_life_url})"
        if wheel_of_life_url
        else "    - Wheel of Life: "
    )
    manifest_line = (
        f"    - [Manifest]({manifest_gdoc_url})\n"
        if manifest_gdoc_url
        else ""
    )
    content = (
        f"---\n"
        f"type:\n"
        f"  - client\n"
        f"status: active\n"
        f'company: "[[{company_name}]]"\n'
        f"tags:\n"
        f"  - client\n"
        f"---\n"
        f"#### History\n"
        f"```dataview\n"
        f"TABLE date AS \"Date\", topic AS \"Topic\", meeting AS \"Meeting\"\n"
        f"FROM \"{_obs_folder('meetings', '8 Meetings')}\"\n"
        f"WHERE contains(client, [[{client_name}]])\n"
        f"SORT date DESC\n"
        f"LIMIT 10\n"
        f"```\n"
        f"\n"
        f"#### {client_name} Reference\n"
        f"\n"
        f"- Personal\n"
        f"- Administrative\n"
        f"    - Billing: \n"
        f"{agreement_line}\n"
        f"{wol_line}\n"
        f"{manifest_line}"
        f"- Goals\n"
        f"    - Development areas: \n"
        f"    - Long-term Vision: \n"
        f"- Insights\n"
        f"- Management & Team\n"
        f"    - Direct Reports\n"
        f"- Decisions on the horizon\n"
    )
    page.write_text(content, encoding="utf-8")
    return page


def _obsidian_project_page(
    vault: Path,
    company_name: str,
    project_name: str,
    billing_type: str,
) -> Path:
    """Write 1 Company/{company_name}/{project_name}.md from the project page template (spec §6.2)."""
    page = vault / _obs_folder("companies", "1 Company") / company_name / f"{project_name}.md"
    if page.exists():
        return page

    content = (
        f"---\n"
        f"type: project\n"
        f"status: active\n"
        f'company: "[[{company_name}]]"\n'
        f"billing_type: {billing_type}\n"
        f"tags:\n"
        f"  - project\n"
        f"---\n"
        f"#### History\n"
        f"```dataview\n"
        f"TABLE date AS \"Date\", topic AS \"Topic\", meeting AS \"Meeting\"\n"
        f"FROM \"{_obs_folder('meetings', '8 Meetings')}\"\n"
        f"WHERE contains(client, [[{project_name}]])\n"
        f"SORT date DESC\n"
        f"LIMIT 10\n"
        f"```\n"
        f"\n"
        f"#### {project_name} Reference\n"
        f"\n"
        f"- Context\n"
        f"- Goals\n"
        f"- Decisions on the horizon\n"
    )
    page.write_text(content, encoding="utf-8")
    return page


# ---------------------------------------------------------------------------
# POST /api/coaching/setup/company
# ---------------------------------------------------------------------------

class CompanyCreateRequest(BaseModel):
    name: str
    abbrev: str | None = None
    default_rate: float | None = None
    billing_method: str | None = None
    payment_method: str | None = None
    ap_email: str | None = None
    cc_email: str | None = None
    notes: str | None = None


@router.post("/setup/company")
def setup_create_company(body: CompanyCreateRequest):
    """Create a new billing company.

    Actions (in order):
    1. Create Google Drive folder under coaching root; on failure → 400 (no DB write)
    2. Insert into billing_companies with gdrive_folder_url
    3. Create Obsidian vault folder + page (failure is a warning, not an error)
    """
    from connectors.drive import create_drive_folder
    from connectors.obsidian import get_vault_path

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Company name is required")

    # 1 — Google Drive folder (must succeed before DB write)
    try:
        folder_id, folder_url = create_drive_folder(name, _drive_root_folder_id())
    except Exception as exc:
        logger.error("Drive folder creation failed for company %r: %s", name, exc)
        raise HTTPException(status_code=400, detail=f"Google Drive error: {exc}")

    # 2 — DB insert
    with get_write_db() as db:
        db.execute(
            """INSERT INTO billing_companies
               (name, abbrev, default_rate, billing_method, payment_method,
                ap_email, cc_email, notes, active, gdrive_folder_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (
                name,
                body.abbrev,
                body.default_rate,
                body.billing_method,
                body.payment_method,
                body.ap_email,
                body.cc_email,
                body.notes,
                folder_url,
            ),
        )
        company_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        db.commit()

    # 3 — Obsidian page (non-fatal)
    obsidian_result = {"action": "skipped", "reason": "vault not configured"}
    obsidian_name = name
    try:
        vault = get_vault_path()
        if vault:
            obsidian_result = _obsidian_company_page(vault, name)
    except Exception as exc:
        logger.warning("Obsidian page creation failed for company %r: %s", name, exc)
        obsidian_result = {"action": "error", "reason": str(exc)}

    # 4 — Append to billing_seed.json (non-fatal)
    try:
        import json as _json
        seed_path = Path(__file__).resolve().parent.parent / "dashy_billing_seed.json"
        if seed_path.exists():
            seed_data = _json.loads(seed_path.read_text(encoding="utf-8"))
            seed_data.setdefault("companies", []).append({
                "name": name,
                "abbrev": body.abbrev,
                "default_rate": body.default_rate,
                "billing_method": body.billing_method,
                "payment_method": body.payment_method,
                "ap_email": body.ap_email,
                "cc_email": body.cc_email,
                "notes": body.notes,
                "gdrive_folder_url": folder_url,
                "obsidian_name": obsidian_name,
                "active": True,
            })
            seed_path.write_text(_json.dumps(seed_data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("Appended company %r to billing_seed.json", name)
    except Exception as exc:
        logger.warning("billing_seed.json update failed for company %r: %s", name, exc)

    logger.info("Created company %r (id=%d) gdrive=%s", name, company_id, folder_url)
    return {
        "status": "ok",
        "company_id": company_id,
        "name": name,
        "gdrive_folder_url": folder_url,
        "obsidian": obsidian_result,
    }


# ---------------------------------------------------------------------------
# Coaching Agreement editor helper
# ---------------------------------------------------------------------------

def _find_text_ranges(body_content: list, target: str) -> list[tuple[int, int]]:
    """Return (startIndex, endIndex) for every occurrence of *target* found
    within individual textRun elements of a Docs API body content list.

    Works for the common case where a placeholder was replaced into a single
    run by replaceAllText.  Cross-run occurrences are not matched.
    """
    ranges: list[tuple[int, int]] = []
    for element in body_content:
        para = element.get("paragraph")
        if not para:
            continue
        for pe in para.get("elements", []):
            tr = pe.get("textRun")
            if not tr:
                continue
            text = tr.get("content", "")
            base = pe.get("startIndex", 0)
            pos = 0
            while True:
                found = text.find(target, pos)
                if found == -1:
                    break
                ranges.append((base + found, base + found + len(target)))
                pos = found + 1
    return ranges


def _edit_coaching_agreement(
    doc_id: str,
    client_first_name: str,
    month_year: str,
    company_name: str,
    manifest_url: str,
    coaching_docs_url: str,
) -> None:
    """Fill in template placeholders in the client's Coaching Agreement doc.

    Plain text substitutions via replaceAllText; hyperlinks via a second
    batchUpdate after fetching the updated document to locate text ranges.
    """
    from connectors.google_auth import get_google_credentials
    from googleapiclient.discovery import build

    creds = get_google_credentials()
    docs_svc = build("docs", "v1", credentials=creds)

    # Pass 1 — plain text + display-text for hyperlink placeholders
    requests: list[dict] = [
        {
            "replaceAllText": {
                "containsText": {"text": "%ClientFirstName%", "matchCase": True},
                "replaceText": client_first_name,
            }
        },
        {
            "replaceAllText": {
                "containsText": {"text": "%monthyear%", "matchCase": True},
                "replaceText": month_year,
            }
        },
        {
            "replaceAllText": {
                "containsText": {"text": "%company%", "matchCase": True},
                "replaceText": company_name,
            }
        },
        {
            "replaceAllText": {
                "containsText": {"text": "%manifest%", "matchCase": True},
                "replaceText": "manifest",
            }
        },
        {
            "replaceAllText": {
                "containsText": {"text": "%sharedfolder%", "matchCase": True},
                "replaceText": "shared folder",
            }
        },
    ]
    docs_svc.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests},
    ).execute()

    # Pass 2 — apply hyperlinks to "manifest" and "shared folder"
    if not manifest_url and not coaching_docs_url:
        return

    doc = docs_svc.documents().get(documentId=doc_id).execute()
    body_content = doc.get("body", {}).get("content", [])

    link_requests: list[dict] = []
    for target, url in [("manifest", manifest_url), ("shared folder", coaching_docs_url)]:
        if not url:
            continue
        for start, end in _find_text_ranges(body_content, target):
            link_requests.append(
                {
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {"link": {"url": url}},
                        "fields": "link",
                    }
                }
            )

    if link_requests:
        docs_svc.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": link_requests},
        ).execute()


# ---------------------------------------------------------------------------
# Manifest doc helper
# ---------------------------------------------------------------------------

_FOLDER_MIME = "application/vnd.google-apps.folder"


def _create_manifest_doc(doc_title: str, coaching_docs_folder_id: str, files: list[dict]) -> tuple[str, str]:
    """Create a Manifest Google Doc inside coaching_docs_folder_id.

    Structure:
        ## Documents
        • {label} (hyperlinked)
        ...

        ## Others

    ``files`` entries must have ``name`` and either ``web_url`` or ``webViewLink``.
    Returns (doc_id, web_view_link).

    Index arithmetic uses UTF-16 code unit offsets (same as the Docs API).
    All characters here are in the Basic Multilingual Plane so len() == code units.
    """
    from connectors.google_auth import get_google_credentials
    from googleapiclient.discovery import build

    creds = get_google_credentials()
    docs_svc = build("docs", "v1", credentials=creds)
    drive_svc = build("drive", "v3", credentials=creds)

    # Create doc (lands in My Drive root by default)
    doc = docs_svc.documents().create(body={"title": doc_title}).execute()
    doc_id = doc["documentId"]

    # Move into the coaching docs folder
    file_meta = drive_svc.files().update(
        fileId=doc_id,
        addParents=coaching_docs_folder_id,
        removeParents="root",
        fields="id, webViewLink",
    ).execute()
    web_view_link = file_meta.get(
        "webViewLink",
        f"https://docs.google.com/document/d/{doc_id}/edit",
    )

    def _label(name: str) -> str:
        return name.rsplit(".", 1)[0] if "." in name else name

    def _url(f: dict) -> str:
        return f.get("web_url") or f.get("webViewLink") or ""

    # Build the full text to insert at index 1 (start of empty doc body)
    parts = ["Documents\n"]
    for f in files:
        parts.append(f"\u2022 {_label(f['name'])}\n")
    parts.append("\n")
    parts.append("Others\n")
    full_text = "".join(parts)

    # Pre-compute index ranges for styling (indices relative to index 1)
    # New doc after creation has one empty paragraph at index 1 ('\n' at 1, endIndex=2).
    # After insertText at index 1 the inserted text sits at 1..1+len(full_text).

    idx = 1

    # "Documents\n"
    docs_h_start = idx
    docs_h_end = idx + len("Documents\n")
    idx = docs_h_end

    # Per-file bullets
    link_ranges: list[tuple[int, int, str]] = []
    for f in files:
        label = _label(f["name"])
        # "• label\n" — bullet (1) + space (1) + label + newline (1)
        label_start = idx + 2          # skip "• "
        label_end = label_start + len(label)
        link_ranges.append((label_start, label_end, _url(f)))
        idx += 2 + len(label) + 1      # "• " + label + "\n"

    idx += 1  # blank line "\n"

    # "Others\n"
    others_h_start = idx
    others_h_end = idx + len("Others\n")

    # Build batchUpdate requests (applied in order after insertText)
    requests: list[dict] = [
        {"insertText": {"location": {"index": 1}, "text": full_text}},
        {
            "updateParagraphStyle": {
                "range": {"startIndex": docs_h_start, "endIndex": docs_h_end},
                "paragraphStyle": {"namedStyleType": "HEADING_2"},
                "fields": "namedStyleType",
            }
        },
        {
            "updateParagraphStyle": {
                "range": {"startIndex": others_h_start, "endIndex": others_h_end},
                "paragraphStyle": {"namedStyleType": "HEADING_2"},
                "fields": "namedStyleType",
            }
        },
    ]
    for start, end, url in link_ranges:
        if url:
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"link": {"url": url}},
                    "fields": "link",
                }
            })

    docs_svc.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests},
    ).execute()

    return doc_id, web_view_link


# ---------------------------------------------------------------------------
# Email template helpers + GET /api/coaching/email-templates
# ---------------------------------------------------------------------------

import time as _time

_EMAIL_TEMPLATES_CACHE: list[dict] | None = None
_EMAIL_TEMPLATES_CACHE_TS: float = 0.0
_EMAIL_TEMPLATES_CACHE_TTL: float = 300.0  # 5 minutes

_WELCOME_TEMPLATE = """\
# welcome
Subject: Welcome to your coaching program with %CoachName%!

<p>Hi %ClientFirstName%,</p>

<p>I'm excited to begin working with you!</p>

<p>Your coaching documents are ready here:</p>

<ul>
  <li><a href="%CoachingDocsUrl%">Coaching Docs folder</a></li>
  <li><a href="%ManifestUrl%">Manifest of coaching documents</a></li>
  <li><a href="%CoachingAgreementUrl%">Coaching agreement</a></li>
  <li><a href="%CoachingKickoffUrl%">Coaching kickoff questions</a></li>
</ul>

<p>Please review the coaching agreement and let me know if there's anything you'd like to change. Let's discuss it when we meet. And take a look at the coaching kickoff questions and see if exploring those are a useful way for us to start.</p>

<p>I'm looking forward to our first session!</p>

<p>Best,<br>
%CoachName%<br>
<a href="mailto:%CoachEmail%">%CoachEmail%</a></p>

<p><a href="%CalendlyLink%">Schedule a session</a></p>
"""


def _get_email_templates_doc_id() -> str | None:
    from app_config import get_install_config
    val = get_install_config().get("google_drive", {}).get("email_templates_doc_id", "")
    return val or None


def _parse_email_templates(text: str) -> list[dict]:
    """Parse # sections from plain-text exported Google Doc.

    Expected format per section::

        # Template Name
        Subject: subject line here

        body text (may contain HTML)

    Sections separated by the next ``# `` heading or ``---`` line.
    """
    templates: list[dict] = []
    # Split on lines that start a new section heading
    sections = re.split(r'\n(?=# )', text.strip())
    for section in sections:
        lines = section.strip().splitlines()
        if not lines:
            continue
        first = lines[0]
        if not first.startswith('# '):
            continue
        name = first[2:].strip()
        if not name:
            continue
        subject_raw = ""
        body_lines: list[str] = []
        in_body = False
        for line in lines[1:]:
            if not in_body:
                if line.startswith('Subject:'):
                    subject_raw = line[len('Subject:'):].strip()
                    in_body = True
                elif line.strip():
                    in_body = True
                    body_lines.append(line)
            else:
                if line.strip() == '---':
                    break
                body_lines.append(line)
        # Strip leading/trailing blank lines from body
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        templates.append({
            'name': name,
            'subject_raw': subject_raw,
            'body_raw': '\n'.join(body_lines),
        })
    return templates


def _fetch_email_templates() -> list[dict]:
    global _EMAIL_TEMPLATES_CACHE, _EMAIL_TEMPLATES_CACHE_TS
    now = _time.time()
    if _EMAIL_TEMPLATES_CACHE is not None and now - _EMAIL_TEMPLATES_CACHE_TS < _EMAIL_TEMPLATES_CACHE_TTL:
        return _EMAIL_TEMPLATES_CACHE

    doc_id = _get_email_templates_doc_id()
    if not doc_id:
        return []

    from connectors.google_auth import get_google_credentials
    from googleapiclient.discovery import build

    creds = get_google_credentials()
    drive_svc = build('drive', 'v3', credentials=creds)
    content_bytes = drive_svc.files().export(fileId=doc_id, mimeType='text/plain').execute()
    text = content_bytes.decode('utf-8-sig', errors='replace') if isinstance(content_bytes, bytes) else str(content_bytes)

    templates = _parse_email_templates(text)
    _EMAIL_TEMPLATES_CACHE = templates
    _EMAIL_TEMPLATES_CACHE_TS = now
    return templates


def _substitute_placeholders(text: str, **subs: str) -> str:
    """Replace %Placeholder% tokens in email template text.

    Supported placeholders and their kwarg keys:
        %ClientFirstName%       — first_name       — client's first name
        %ClientFullName%        — full_name         — client's full name
        %Company%               — company           — company name
        %CoachingDocsUrl%       — coaching_docs_url — URL of the Coaching Docs folder
        %ManifestUrl%           — manifest_url      — URL of the Manifest Google Doc
        %CoachingAgreementUrl%  — coaching_agreement_url — URL of the Coaching Agreement file
        %CoachingKickoffUrl%    — coaching_kickoff_url   — URL of the Coaching Kickoff Questions file
        %CalendlyLink%          — calendly_link     — coach's Calendly URL (dashy_install.json user.calendly_url)
        %CoachEmail%            — coach_email       — coach's email (dashy_install.json user.coach_email)
        %CoachName%             — coach_name        — coach's display name (dashy_install.json user.name)
        %MonthYear%             — month_year        — current month and year, e.g. "April 2026"
    """
    mapping = {
        '%ClientFirstName%': subs.get('first_name', ''),
        '%ClientFullName%': subs.get('full_name', ''),
        '%Company%': subs.get('company', ''),
        '%CoachingDocsUrl%': subs.get('coaching_docs_url', ''),
        '%ManifestUrl%': subs.get('manifest_url', ''),
        '%CoachingAgreementUrl%': subs.get('coaching_agreement_url', ''),
        '%CoachingKickoffUrl%': subs.get('coaching_kickoff_url', ''),
        '%CalendlyLink%': subs.get('calendly_link', ''),
        '%CoachEmail%': subs.get('coach_email', ''),
        '%CoachName%': subs.get('coach_name', ''),
        '%MonthYear%': subs.get('month_year', ''),
    }
    for placeholder, value in mapping.items():
        text = text.replace(placeholder, value)
    return text


def _create_gmail_draft_html(to: str, subject: str, html_body: str) -> dict:
    """Create a Gmail draft with an HTML body. Returns {id, message_id}."""
    import base64 as _b64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText as _MIMEText
    from connectors.google_auth import get_google_credentials
    from googleapiclient.discovery import build

    creds = get_google_credentials()
    service = build('gmail', 'v1', credentials=creds)

    message = MIMEMultipart('alternative')
    message['to'] = to
    message['subject'] = subject
    message.attach(_MIMEText(html_body, 'html'))

    raw = _b64.urlsafe_b64encode(message.as_bytes()).decode()
    result = service.users().drafts().create(userId='me', body={'message': {'raw': raw}}).execute()
    return {
        'id': result.get('id', ''),
        'message_id': result.get('message', {}).get('id', ''),
    }


@router.get("/email-templates")
def get_email_templates():
    """Return parsed templates from the Email Templates Google Doc."""
    doc_id = _get_email_templates_doc_id()
    if not doc_id:
        return {'templates': [], 'configured': False}
    try:
        templates = _fetch_email_templates()
        return {'templates': templates, 'configured': True}
    except Exception as exc:
        logger.warning('Failed to fetch email templates: %s', exc)
        return {'templates': [], 'configured': True, 'error': str(exc)}


@router.post("/setup/email-templates/init")
def init_email_templates_doc():
    """Create the Email Templates Google Doc in the coaching root folder.

    Idempotent — returns existing doc_id if already configured.
    After running, ``dashy_install.json`` is updated with the new doc_id
    and the in-process config cache is cleared.
    """
    import json as _json
    import app_config
    from connectors.google_auth import get_google_credentials
    from googleapiclient.discovery import build

    existing_id = _get_email_templates_doc_id()
    if existing_id:
        return {'status': 'already_configured', 'doc_id': existing_id}

    folder_id = '1NU2M79IKQ7P-6Laebh286wLcJfoJXKcz'

    creds = get_google_credentials()
    docs_svc = build('docs', 'v1', credentials=creds)
    drive_svc = build('drive', 'v3', credentials=creds)

    # Create doc
    doc = docs_svc.documents().create(body={'title': 'Email Templates'}).execute()
    doc_id = doc['documentId']

    # Move into coaching root folder
    drive_svc.files().update(
        fileId=doc_id,
        addParents=folder_id,
        removeParents='root',
        fields='id, webViewLink',
    ).execute()

    # Insert initial welcome template content
    docs_svc.documents().batchUpdate(
        documentId=doc_id,
        body={'requests': [{'insertText': {'location': {'index': 1}, 'text': _WELCOME_TEMPLATE.strip()}}]},
    ).execute()

    # Persist to dashy_install.json
    install_path = app_config._REPO_ROOT / 'dashy_install.json'
    install_data = _json.loads(install_path.read_text())
    install_data.setdefault('google_drive', {})['email_templates_doc_id'] = doc_id
    install_path.write_text(_json.dumps(install_data, indent=2, ensure_ascii=False))

    # Bust the in-process cache so GET /email-templates picks up the new ID
    with app_config._file_lock:
        app_config._install_cache = None

    logger.info('Created Email Templates doc %s in folder %s', doc_id, folder_id)
    return {
        'status': 'created',
        'doc_id': doc_id,
        'web_url': f'https://docs.google.com/document/d/{doc_id}/edit',
    }


@router.post("/setup/email-templates/rewrite")
def rewrite_email_templates_doc():
    """Clear the Email Templates Google Doc and rewrite it with the current _WELCOME_TEMPLATE.

    Use this after updating _WELCOME_TEMPLATE in code to push the new content to the live doc.
    Busts the in-process template cache on success.
    """
    global _EMAIL_TEMPLATES_CACHE, _EMAIL_TEMPLATES_CACHE_TS

    from connectors.google_auth import get_google_credentials
    from googleapiclient.discovery import build

    doc_id = _get_email_templates_doc_id()
    if not doc_id:
        raise HTTPException(status_code=400, detail="email_templates_doc_id not configured in dashy_install.json")

    creds = get_google_credentials()
    docs_svc = build('docs', 'v1', credentials=creds)

    doc = docs_svc.documents().get(documentId=doc_id).execute()
    end_index = doc['body']['content'][-1]['endIndex'] - 1

    requests: list[dict] = []
    if end_index > 1:
        requests.append({'deleteContentRange': {'range': {'startIndex': 1, 'endIndex': end_index}}})
    requests.append({'insertText': {'location': {'index': 1}, 'text': _WELCOME_TEMPLATE.strip()}})

    docs_svc.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()

    # Bust the in-process template cache
    _EMAIL_TEMPLATES_CACHE = None
    _EMAIL_TEMPLATES_CACHE_TS = 0.0

    logger.info('Rewrote Email Templates doc %s', doc_id)
    return {
        'status': 'ok',
        'doc_id': doc_id,
        'web_url': f'https://docs.google.com/document/d/{doc_id}/edit',
    }


# ---------------------------------------------------------------------------
# POST /api/coaching/setup/client
# ---------------------------------------------------------------------------

class ClientCreateRequest(BaseModel):
    company_id: int
    name: str
    obsidian_name: str | None = None
    email: str | None = None
    rate_override: float | None = None
    prepaid: bool = False
    email_template: str | None = None


def _run_client_creation(task_id: str, body: "ClientCreateRequest") -> None:
    """Background thread: executes the full client creation pipeline and
    updates _client_tasks[task_id] with live step progress and final result.
    """
    from connectors.drive import copy_drive_file, get_or_create_drive_folder, list_drive_files
    from connectors.obsidian import get_vault_path

    task = _client_tasks[task_id]

    def _step(name: str, status: str, detail: str = "") -> None:
        task["steps"].append({"name": name, "status": status, "detail": detail})

    def _finish_step(status: str, detail: str = "") -> None:
        if task["steps"]:
            task["steps"][-1]["status"] = status
            if detail:
                task["steps"][-1]["detail"] = detail

    def _fatal(name: str, detail: str) -> None:
        _finish_step("error", detail)
        task["done"] = True
        task["error"] = detail

    name = body.name.strip()
    obsidian_name = (body.obsidian_name or name).strip()

    # Step 1 — Validate company (read directly from billing_companies by ID)
    _step("Validate company", "running")
    try:
        db_r = get_db()
        # Look up by ID only — do NOT filter by active so Setup-created companies
        # (which may not yet be in billing_seed.json) are always found.
        company = db_r.execute(
            "SELECT id, name, gdrive_folder_url, billing_method FROM billing_companies WHERE id = ?",
            (body.company_id,),
        ).fetchone()
        db_r.close()
        if not company:
            return _fatal("Validate company", f"Company id={body.company_id} not found in DB")
        company_name = company["name"]
        company_billing_method = company["billing_method"] or ""
        company_folder_id = _folder_id_from_url(company["gdrive_folder_url"] or "")
        if not company_folder_id:
            return _fatal("Validate company", f"Company '{company_name}' has no Drive folder configured")
        _finish_step("ok", company_name)
    except Exception as exc:
        return _fatal("Validate company", str(exc))

    # Step 2 — Create Drive folders
    _step("Create Drive folders", "running")
    try:
        clients_folder_id, _ = get_or_create_drive_folder(_drive_subfolder("clients", "Clients"), company_folder_id)
        client_folder_id, _ = get_or_create_drive_folder(name, clients_folder_id)
        coaching_docs_id, coaching_docs_url = get_or_create_drive_folder(
            _drive_subfolder("coaching_docs", "Coaching docs"), client_folder_id
        )
        _finish_step("ok")
    except Exception as exc:
        logger.error("Drive folder creation failed for client %r: %s", name, exc)
        return _fatal("Create Drive folders", str(exc))

    # Step 3 — Copy template files (non-fatal)
    _step("Copy template files", "running")
    coaching_agreement_url = ""
    coaching_agreement_doc_id: str | None = None
    coaching_kickoff_url = ""
    wheel_of_life_url = ""
    copied_files: list[dict] = []
    try:
        template_files = list_drive_files(_drive_template_folder_id())
        for tf in template_files:
            copied = copy_drive_file(tf["id"], coaching_docs_id, original_name=tf["name"])
            copied_files.append(copied)
            lower = copied["name"].lower()
            if "coaching agreement" in lower or "agreement" in lower:
                coaching_agreement_url = copied["web_url"]
                coaching_agreement_doc_id = copied["id"]
            elif "kickoff" in lower:
                coaching_kickoff_url = copied["web_url"]
            elif "wheel of life" in lower or "wheel" in lower:
                wheel_of_life_url = copied["web_url"]
        _finish_step("ok", f"{len(copied_files)} files")
    except Exception as exc:
        logger.warning("Template file copy incomplete for client %r: %s", name, exc)
        _finish_step("warning", str(exc))

    # Step 5 — Save to database (fatal if fails)
    _step("Save to database", "running")
    try:
        with get_write_db() as db:
            db.execute(
                """INSERT INTO billing_clients
                   (name, company_id, rate_override, prepaid, obsidian_name,
                    email, status, client_type, gdrive_coaching_docs_url)
                   VALUES (?, ?, ?, ?, ?, ?, 'active', 'company', ?)""",
                (
                    name,
                    body.company_id,
                    body.rate_override,
                    int(body.prepaid),
                    obsidian_name,
                    body.email,
                    coaching_docs_url,
                ),
            )
            client_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            db.commit()
        _finish_step("ok", f"id={client_id}")
    except Exception as exc:
        logger.error("DB insert failed for client %r: %s", name, exc)
        return _fatal("Save to database", str(exc))

    # Step 6 — Set client type from company billing_method (non-fatal)
    _step("Set client type", "running")
    new_type = "individual" if company_billing_method in ("payasgo", "individual") else "company"
    try:
        with get_write_db() as db:
            db.execute(
                "UPDATE billing_clients SET client_type = ? WHERE id = ?",
                (new_type, client_id),
            )
            db.commit()
        _finish_step("ok", new_type)
    except Exception as exc:
        logger.warning("Client type detection failed for client %r: %s", name, exc)
        _finish_step("warning", str(exc))

    # Step 7 — Create Manifest doc (non-fatal)
    _step("Create Manifest doc", "running")
    manifest_gdoc_url: str | None = None
    try:
        doc_title = f"Manifest - {name}"
        _, manifest_gdoc_url = _create_manifest_doc(doc_title, coaching_docs_id, copied_files)
        with get_write_db() as db:
            db.execute(
                "UPDATE billing_clients SET manifest_gdoc_url = ? WHERE id = ?",
                (manifest_gdoc_url, client_id),
            )
            db.commit()
        logger.info("Created Manifest doc for client %r: %s", name, manifest_gdoc_url)
        _finish_step("ok")
    except Exception as exc:
        logger.warning("Manifest doc creation failed for client %r: %s", name, exc)
        _finish_step("warning", str(exc))

    # Step 8 — Edit Coaching Agreement (non-fatal, skip if no agreement)
    agreement_edited = False
    if coaching_agreement_doc_id:
        _step("Edit Coaching Agreement", "running")
        try:
            from datetime import date as _date
            month_year = _date.today().strftime("%B %Y")
            _edit_coaching_agreement(
                doc_id=coaching_agreement_doc_id,
                client_first_name=name.split()[0],
                month_year=month_year,
                company_name=company_name,
                manifest_url=manifest_gdoc_url or "",
                coaching_docs_url=coaching_docs_url,
            )
            agreement_edited = True
            _finish_step("ok")
            logger.info("Edited Coaching Agreement for client %r", name)
        except Exception as exc:
            logger.warning("Coaching Agreement edit failed for client %r: %s", name, exc)
            _finish_step("warning", str(exc))

    # Step 9 — Create Obsidian page (non-fatal)
    _step("Create Obsidian page", "running")
    obsidian_result: dict = {"action": "skipped", "reason": "vault not configured"}
    try:
        vault = get_vault_path()
        if vault:
            page = _obsidian_client_page(
                vault, obsidian_name, company_name,
                coaching_agreement_url, wheel_of_life_url,
                manifest_gdoc_url=manifest_gdoc_url or "",
            )
            obsidian_result = {"action": "created", "path": str(page)}
            _finish_step("ok", obsidian_name)
        else:
            _finish_step("ok", "vault not configured")
    except Exception as exc:
        logger.warning("Obsidian client page failed for %r: %s", name, exc)
        obsidian_result = {"action": "error", "reason": str(exc)}
        _finish_step("warning", str(exc))

    # Step 10 — Update billing seed (non-fatal, skip if file absent)
    try:
        seed_path = Path(__file__).resolve().parent.parent / "dashy_billing_seed.json"
        if seed_path.exists():
            _step("Update billing seed", "running")
            import json as _json
            seed_data = _json.loads(seed_path.read_text(encoding="utf-8"))
            seed_data.setdefault("clients", []).append({
                "name": name, "company": company_name, "obsidian_name": obsidian_name,
                "email": body.email or None, "rate_override": body.rate_override,
                "prepaid": body.prepaid, "client_type": new_type,
                "gdrive_coaching_docs_url": coaching_docs_url,
                "manifest_gdoc_url": manifest_gdoc_url, "active": True,
            })
            seed_path.write_text(_json.dumps(seed_data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("Appended client %r to billing_seed.json", name)
            _finish_step("ok")
    except Exception as exc:
        logger.warning("billing_seed.json update failed for client %r: %s", name, exc)
        if task["steps"] and task["steps"][-1]["name"] == "Update billing seed":
            _finish_step("warning", str(exc))

    # Step 11 — Create email draft (non-fatal, skip if no template/email)
    draft_id: str | None = None
    draft_url: str | None = None
    if body.email_template and body.email:
        _step("Create email draft", "running")
        try:
            from app_config import get_install_config
            from datetime import date as _date
            _cfg = get_install_config()
            coach_name = _cfg.get("user", {}).get("name", "Your Coach")
            coach_email = _cfg.get("user", {}).get("coach_email", "")
            calendly_link = _cfg.get("user", {}).get("calendly_url", "")
            month_year = _date.today().strftime("%B %Y")
            client_first_name = name.split()[0]
            templates = _fetch_email_templates()
            matched = next((t for t in templates if t["name"].lower() == body.email_template.lower()), None)
            if matched:
                _subs = dict(
                    first_name=client_first_name, full_name=name,
                    company=company_name, coaching_docs_url=coaching_docs_url,
                    manifest_url=manifest_gdoc_url or "",
                    coaching_agreement_url=coaching_agreement_url,
                    coaching_kickoff_url=coaching_kickoff_url,
                    calendly_link=calendly_link,
                    coach_email=coach_email, coach_name=coach_name, month_year=month_year,
                )
                subject = _substitute_placeholders(matched["subject_raw"], **_subs)
                body_html = _substitute_placeholders(matched["body_raw"], **_subs)
                draft = _create_gmail_draft_html(body.email, subject, body_html)
                draft_id = draft["id"]
                draft_url = f"https://mail.google.com/mail/#drafts/{draft_id}"
                logger.info("Created email draft %s for client %r", draft_id, name)
                _finish_step("ok")
            else:
                logger.warning("Email template %r not found for client %r", body.email_template, name)
                _finish_step("warning", f"Template '{body.email_template}' not found")
        except Exception as exc:
            logger.warning("Email draft creation failed for client %r: %s", name, exc)
            _finish_step("warning", str(exc))

    logger.info(
        "Created client %r (id=%d) company=%r coaching_docs=%s client_type=%s",
        name, client_id, company_name, coaching_docs_url, new_type,
    )
    task["result"] = {
        "status": "ok",
        "client_id": client_id,
        "name": name,
        "company_name": company_name,
        "client_type": new_type,
        "gdrive_coaching_docs_url": coaching_docs_url,
        "copied_files": [f["name"] for f in copied_files],
        "manifest_gdoc_url": manifest_gdoc_url,
        "agreement_edited": agreement_edited,
        "obsidian": obsidian_result,
        "obsidian_name": obsidian_name,
        "draft_id": draft_id,
        "draft_url": draft_url,
    }
    task["done"] = True


@router.post("/setup/client")
def setup_create_client(body: ClientCreateRequest):
    """Kick off async client creation. Returns task_id for progress polling."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Client name is required")
    task_id = str(uuid.uuid4())
    _client_tasks[task_id] = {"steps": [], "done": False, "result": None, "error": None}
    t = threading.Thread(target=_run_client_creation, args=(task_id, body), daemon=True)
    t.start()
    return {"task_id": task_id}


@router.get("/setup/client/status/{task_id}")
def setup_client_status(task_id: str):
    """Poll progress of an async client creation task."""
    task = _client_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ---------------------------------------------------------------------------
# POST /api/coaching/setup/project
# ---------------------------------------------------------------------------

class ProjectCreateRequest(BaseModel):
    company_id: int
    name: str
    obsidian_name: str | None = None
    billing_type: str = "hourly"   # "hourly" | "fixed"
    fixed_amount: float | None = None
    rate_override: float | None = None


@router.post("/setup/project")
def setup_create_project(body: ProjectCreateRequest):
    """Create a new billing project.

    Actions (in order):
    1. Validate company exists and has gdrive_folder_url
    2. Create Drive {company}/Projects/{project_name}/ folder; on failure → 400 (no DB write)
    3. Insert into billing_projects with gdrive_folder_url
    4. Create Obsidian project page in 1 Company/{company_name}/ (failure is a warning)
    """
    from connectors.drive import get_or_create_drive_folder
    from connectors.obsidian import get_vault_path

    name = body.name.strip()
    obsidian_name = (body.obsidian_name or name).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required")

    billing_type = body.billing_type if body.billing_type in ("hourly", "fixed") else "hourly"

    db_r = get_db()
    company = db_r.execute(
        "SELECT id, name, gdrive_folder_url FROM billing_companies WHERE id = ? AND active = 1",
        (body.company_id,),
    ).fetchone()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company_name = company["name"]
    company_folder_url = company["gdrive_folder_url"]
    company_folder_id = _folder_id_from_url(company_folder_url) if company_folder_url else None

    if not company_folder_id:
        raise HTTPException(
            status_code=400,
            detail=f"Company '{company_name}' has no Google Drive folder configured. "
                   "Create the company via Setup first.",
        )

    # 1 — Drive folder (must succeed before DB write)
    try:
        projects_folder_id, _ = get_or_create_drive_folder(_drive_subfolder("projects", "Projects"), company_folder_id)
        project_folder_id, project_folder_url = get_or_create_drive_folder(name, projects_folder_id)
    except Exception as exc:
        logger.error("Drive folder creation failed for project %r: %s", name, exc)
        raise HTTPException(status_code=400, detail=f"Google Drive error: {exc}")

    # 2 — DB insert
    with get_write_db() as db:
        db.execute(
            """INSERT INTO billing_projects
               (name, company_id, billing_type, fixed_amount, rate_override,
                obsidian_name, gdrive_folder_url, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                name,
                body.company_id,
                billing_type,
                body.fixed_amount,
                body.rate_override,
                obsidian_name,
                project_folder_url,
            ),
        )
        project_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        db.commit()

    # 3 — Obsidian page (non-fatal)
    obsidian_result: dict = {"action": "skipped", "reason": "vault not configured"}
    try:
        vault = get_vault_path()
        if vault:
            page = _obsidian_project_page(vault, company_name, obsidian_name, billing_type)
            obsidian_result = {"action": "created", "path": str(page)}
    except Exception as exc:
        logger.warning("Obsidian project page failed for %r: %s", name, exc)
        obsidian_result = {"action": "error", "reason": str(exc)}

    # 4 — Append to billing_seed.json (non-fatal)
    try:
        import json as _json
        seed_path = Path(__file__).resolve().parent.parent / "dashy_billing_seed.json"
        if seed_path.exists():
            seed_data = _json.loads(seed_path.read_text(encoding="utf-8"))
            seed_data.setdefault("projects", []).append({
                "name": name,
                "company": company_name,
                "billing_type": billing_type,
                "fixed_amount": body.fixed_amount,
                "rate_override": body.rate_override,
                "obsidian_name": obsidian_name,
                "gdrive_folder_url": project_folder_url,
                "gdrive_coaching_docs_url": "",
                "active": True,
            })
            seed_path.write_text(_json.dumps(seed_data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("Appended project %r to billing_seed.json", name)
    except Exception as exc:
        logger.warning("billing_seed.json update failed for project %r: %s", name, exc)

    logger.info(
        "Created project %r (id=%d) company=%r drive=%s",
        name, project_id, company_name, project_folder_url,
    )
    return {
        "status": "ok",
        "project_id": project_id,
        "name": name,
        "company_name": company_name,
        "billing_type": billing_type,
        "gdrive_folder_url": project_folder_url,
        "obsidian": obsidian_result,
    }


# ---------------------------------------------------------------------------
# POST /api/coaching/setup/create-manifests
# ---------------------------------------------------------------------------

@router.post("/setup/create-manifests")
def create_missing_manifests():
    """Create Manifest Google Docs for all active clients that lack one.

    For each active client where manifest_gdoc_url IS NULL:
      1. Skip if no gdrive_coaching_docs_url
      2. List files in the Coaching Docs folder (excluding sub-folders and
         any existing Manifest docs)
      3. Create "Manifest - {name}" doc with Documents + Others sections
      4. Update billing_clients.manifest_gdoc_url

    Returns a per-client result list with status, name, and manifest_url/error.
    """
    from connectors.drive import list_drive_files

    db = get_db()
    clients = db.execute(
        """SELECT id, name, gdrive_coaching_docs_url
           FROM billing_clients
           WHERE active = 1 AND (manifest_gdoc_url IS NULL OR manifest_gdoc_url = '')
           ORDER BY name""",
    ).fetchall()

    results: list[dict] = []
    for client in clients:
        client_id = client["id"]
        client_name = client["name"]
        coaching_docs_url = client["gdrive_coaching_docs_url"]

        if not coaching_docs_url:
            results.append({
                "client_id": client_id,
                "name": client_name,
                "status": "skipped",
                "reason": "no coaching_docs folder",
                "manifest_url": None,
            })
            continue

        coaching_docs_id = _folder_id_from_url(coaching_docs_url)
        if not coaching_docs_id:
            results.append({
                "client_id": client_id,
                "name": client_name,
                "status": "skipped",
                "reason": "invalid coaching_docs URL",
                "manifest_url": None,
            })
            continue

        try:
            all_files = list_drive_files(coaching_docs_id)
            # Exclude sub-folders and any existing Manifest docs
            doc_files = [
                f for f in all_files
                if f.get("mimeType") != _FOLDER_MIME
                and "manifest" not in f.get("name", "").lower()
            ]

            doc_title = f"Manifest - {client_name}"
            _, manifest_url = _create_manifest_doc(doc_title, coaching_docs_id, doc_files)

            with get_write_db() as wdb:
                wdb.execute(
                    "UPDATE billing_clients SET manifest_gdoc_url = ? WHERE id = ?",
                    (manifest_url, client_id),
                )
                wdb.commit()

            logger.info("Retroactive manifest created for client %r: %s", client_name, manifest_url)
            results.append({
                "client_id": client_id,
                "name": client_name,
                "status": "created",
                "manifest_url": manifest_url,
            })
        except Exception as exc:
            logger.error("Manifest creation failed for client %r: %s", client_name, exc)
            results.append({
                "client_id": client_id,
                "name": client_name,
                "status": "error",
                "error": str(exc),
                "manifest_url": None,
            })

    return {
        "total": len(results),
        "created": sum(1 for r in results if r["status"] == "created"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }


# ---------------------------------------------------------------------------
# GET /api/coaching/clients/{client_id}/synopsis
# ---------------------------------------------------------------------------

def _summarize_session_note(obsidian_name: str | None, date_str: str, note_path: str | None) -> str:
    """Read an Obsidian meeting note and generate a 2-3 sentence Claude summary."""
    from connectors.obsidian import get_vault_path
    vault = get_vault_path()
    if not vault:
        return "Note not available"

    if note_path:
        full_path = vault / note_path
    elif obsidian_name:
        full_path = vault / "8 Meetings" / f"{date_str} - {obsidian_name}.md"
    else:
        return "Note not available"

    if not full_path.exists():
        return "Note not available"

    try:
        content = full_path.read_text(encoding="utf-8")
    except Exception:
        return "Note not available"

    try:
        import anthropic
        from app_config import get_secret
        client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    "Summarize this coaching session note in 2-3 sentences. "
                    "Focus on key topics discussed, decisions made, and any commitments or actions. "
                    "Be concise and specific.\n\n" + content
                ),
            }],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        logger.warning("Claude synopsis summary failed: %s", exc)
        return "Summary unavailable"


@router.get("/clients/{client_id}/synopsis")
def get_client_synopsis(client_id: int):
    """Pre-meeting briefing card for a coaching client."""
    db = get_db()

    client = db.execute(
        """
        SELECT bc.id, bc.name, bc.obsidian_name,
               bc.gdrive_coaching_docs_url, bc.manifest_gdoc_url,
               bc.coaching_agreement_url, bc.shared_notes_url,
               bco.name AS company_name
        FROM billing_clients bc
        JOIN billing_companies bco ON bc.company_id = bco.id
        WHERE bc.id = ?
        """,
        (client_id,),
    ).fetchone()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Last 3 confirmed sessions (most recent first)
    past_rows = db.execute(
        """
        SELECT date, session_number, obsidian_note_path
        FROM billing_sessions
        WHERE client_id = ? AND is_confirmed = 1 AND (canceled IS NULL OR canceled = 0)
        ORDER BY date DESC LIMIT 3
        """,
        (client_id,),
    ).fetchall()

    # Next 2 upcoming sessions (future billing_sessions, unconfirmed)
    future_rows = db.execute(
        """
        SELECT bs.date, bs.session_number, ce.summary AS event_title
        FROM billing_sessions bs
        LEFT JOIN calendar_events ce ON bs.calendar_event_id = ce.id
        WHERE bs.client_id = ?
          AND bs.date >= date('now')
          AND (bs.canceled IS NULL OR bs.canceled = 0)
        ORDER BY bs.date ASC LIMIT 2
        """,
        (client_id,),
    ).fetchall()

    today = date.today()
    obsidian_name = client["obsidian_name"]

    past_sessions = []
    for row in past_rows:
        d = date.fromisoformat(row["date"])
        past_sessions.append({
            "date": row["date"],
            "day_label": d.strftime("%a %b %-d"),
            "session_number": row["session_number"],
            "obsidian_note_path": row["obsidian_note_path"],
            "summary": _summarize_session_note(obsidian_name, row["date"], row["obsidian_note_path"]),
        })

    future_sessions = []
    for row in future_rows:
        d = date.fromisoformat(row["date"])
        days_until = (d - today).days
        future_sessions.append({
            "date": row["date"],
            "day_label": d.strftime("%a %b %-d"),
            "days_until": days_until,
            "event_title": row["event_title"] or "",
        })

    return {
        "client": {
            "id": client["id"],
            "name": client["name"],
            "obsidian_name": client["obsidian_name"],
            "company_name": client["company_name"],
            "gdrive_coaching_docs_url": client["gdrive_coaching_docs_url"],
            "manifest_gdoc_url": client["manifest_gdoc_url"],
            "coaching_agreement_url": client["coaching_agreement_url"],
            "shared_notes_url": client["shared_notes_url"],
        },
        "past_sessions": past_sessions,
        "future_sessions": future_sessions,
    }
