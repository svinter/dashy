import json
import logging
import re
import threading
import traceback
from datetime import date, datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db, get_write_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/coaching", tags=["coaching"])

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
            bco.id   AS company_id,
            bco.name AS company_name,
            bco.default_rate
        FROM billing_clients bc
        JOIN billing_companies bco ON bc.company_id = bco.id
        WHERE bc.active = 1
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
        "FROM billing_clients WHERE active = 1"
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
                    note_path = f"8 Meetings/{fname}"
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
    today = date.today()
    today_str = today.isoformat()

    # Vault path for disk-based note existence checks (future/days modes)
    vault_meetings = None
    try:
        from connectors.obsidian import get_vault_path
        _vault = get_vault_path()
        if _vault:
            vault_meetings = _vault / "8 Meetings"
    except Exception:
        pass

    # Monday of current week
    week_start = today - __import__('datetime').timedelta(days=today.weekday())
    week_end = week_start + __import__('datetime').timedelta(days=6)

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
            ORDER BY ce.start_time ASC
            """,
            [today_str],
        ).fetchall()

    elif mode == "next":
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
            WHERE bs.date >= ?
              AND bs.client_id IS NOT NULL
              AND bs.color_id = '5'
              AND bs.is_confirmed = 0
            ORDER BY bs.date ASC, ce.start_time ASC
            LIMIT 10
            """,
            [today_str],
        ).fetchall()

    elif mode == "week":
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
            WHERE bs.date BETWEEN ? AND ?
              AND bs.client_id IS NOT NULL
              AND bs.color_id IN ('5', '11')
            ORDER BY bs.date ASC, ce.start_time ASC
            """,
            [week_start.isoformat(), week_end.isoformat()],
        ).fetchall()

    elif mode == "future":
        # Show grape/banana events remaining today if any exist after now; else tomorrow only.
        now_str = datetime.now().isoformat()
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
            from datetime import timedelta
            future_submode = "tomorrow"
            target_date = (today + timedelta(days=1)).isoformat()

        raw_rows = db.execute(
            _CE_SESSION_SELECT +
            "WHERE ce.color_id IN ('3', '5') AND date(ce.start_time) = ? "
            "ORDER BY ce.start_time ASC",
            [target_date],
        ).fetchall()
        rows = _enrich_event_rows(raw_rows, db, vault_meetings)

    else:
        # ;N days mode (days param)
        from datetime import timedelta
        end_date = today + timedelta(days=days)
        raw_rows = db.execute(
            _CE_SESSION_SELECT +
            "WHERE ce.color_id IN ('3', '5') "
            "AND date(ce.start_time) BETWEEN ? AND ? "
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
    meetings_dir = vault / "8 Meetings"

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
                            "path": f"8 Meetings/{date_str} - {obsidian_name}.md",
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
                            "path": f"8 Meetings/{date_str} - {obsidian_name}.md",
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


# ---------------------------------------------------------------------------
# Setup — shared constants and helpers
# ---------------------------------------------------------------------------

_DRIVE_ROOT_FOLDER_ID = "1Y6zVoKjaCOSs2PJTPSwAELUUBOv7PBy3"
_DRIVE_TEMPLATE_FOLDER_ID = "1ejHI_5Y6lghWVL22ztV1O3YMRxxQeiHo"


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
    folder = vault / "1 Company" / company_name
    page = folder / f"{company_name}.md"
    flat = vault / "1 Company" / f"{company_name}.md"

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
) -> Path:
    """Write 1 People/{client_name}.md from the client page template (spec §6.1)."""
    page = vault / "1 People" / f"{client_name}.md"
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
        f"[dataview: meetings for this client, sorted by date desc]\n"
        f"\n"
        f"#### {client_name} Reference\n"
        f"\n"
        f"- Personal\n"
        f"- Administrative\n"
        f"    - Billing: \n"
        f"{agreement_line}\n"
        f"{wol_line}\n"
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
    page = vault / "1 Company" / company_name / f"{project_name}.md"
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
        f"[dataview: meetings for this project, sorted by date desc]\n"
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
        folder_id, folder_url = create_drive_folder(name, _DRIVE_ROOT_FOLDER_ID)
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
    try:
        vault = get_vault_path()
        if vault:
            obsidian_result = _obsidian_company_page(vault, name)
    except Exception as exc:
        logger.warning("Obsidian page creation failed for company %r: %s", name, exc)
        obsidian_result = {"action": "error", "reason": str(exc)}

    logger.info("Created company %r (id=%d) gdrive=%s", name, company_id, folder_url)
    return {
        "status": "ok",
        "company_id": company_id,
        "name": name,
        "gdrive_folder_url": folder_url,
        "obsidian": obsidian_result,
    }


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
# POST /api/coaching/setup/client
# ---------------------------------------------------------------------------

class ClientCreateRequest(BaseModel):
    company_id: int
    name: str
    obsidian_name: str | None = None
    email: str | None = None
    rate_override: float | None = None
    prepaid: bool = False


@router.post("/setup/client")
def setup_create_client(body: ClientCreateRequest):
    """Create a new billing client.

    Actions (in order):
    1. Validate company exists and has gdrive_folder_url
    2. Create Drive folder structure + copy template files; on failure → 400 (no DB write)
    3. Insert into billing_clients with gdrive_coaching_docs_url
    4. Update client_type for all clients at this company (auto-detection)
    5. Create Obsidian client page (failure is a warning)
    """
    from connectors.drive import copy_drive_file, create_drive_folder, list_drive_files
    from connectors.obsidian import get_vault_path

    name = body.name.strip()
    obsidian_name = (body.obsidian_name or name).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Client name is required")

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

    # 1 — Drive folder structure (must succeed before DB write)
    try:
        # {company}/Clients/{client_name}/
        clients_folder_id, _ = create_drive_folder("Clients", company_folder_id)
        client_folder_id, _ = create_drive_folder(name, clients_folder_id)
        # {company}/Clients/{client_name}/Coaching docs/
        coaching_docs_id, coaching_docs_url = create_drive_folder("Coaching docs", client_folder_id)
    except Exception as exc:
        logger.error("Drive folder creation failed for client %r: %s", name, exc)
        raise HTTPException(status_code=400, detail=f"Google Drive error: {exc}")

    # 2 — Copy template files into Coaching docs
    coaching_agreement_url = ""
    wheel_of_life_url = ""
    copied_files: list[dict] = []
    try:
        template_files = list_drive_files(_DRIVE_TEMPLATE_FOLDER_ID)
        for tf in template_files:
            copied = copy_drive_file(tf["id"], coaching_docs_id)
            copied_files.append(copied)
            lower = copied["name"].lower()
            if "coaching agreement" in lower or "agreement" in lower:
                coaching_agreement_url = copied["web_url"]
            elif "wheel of life" in lower or "wheel" in lower:
                wheel_of_life_url = copied["web_url"]
    except Exception as exc:
        logger.warning("Template file copy incomplete for client %r: %s", name, exc)

    # 3 — DB insert
    with get_write_db() as db:
        db.execute(
            """INSERT INTO billing_clients
               (name, company_id, rate_override, prepaid, obsidian_name,
                email, active, client_type, gdrive_coaching_docs_url)
               VALUES (?, ?, ?, ?, ?, ?, 1, 'company', ?)""",
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

    # 4 — client_type auto-detection
    with get_write_db() as db:
        count_row = db.execute(
            "SELECT COUNT(*) AS cnt FROM billing_clients WHERE company_id = ? AND active = 1",
            (body.company_id,),
        ).fetchone()
        active_count = count_row["cnt"] if count_row else 1

        new_type = "individual" if active_count == 1 else "company"
        db.execute(
            "UPDATE billing_clients SET client_type = ? WHERE company_id = ? AND active = 1",
            (new_type, body.company_id),
        )
        db.commit()

    # 5 — Obsidian page (non-fatal)
    obsidian_result: dict = {"action": "skipped", "reason": "vault not configured"}
    try:
        vault = get_vault_path()
        if vault:
            page = _obsidian_client_page(
                vault, obsidian_name, company_name,
                coaching_agreement_url, wheel_of_life_url,
            )
            obsidian_result = {"action": "created", "path": str(page)}
    except Exception as exc:
        logger.warning("Obsidian client page failed for %r: %s", name, exc)
        obsidian_result = {"action": "error", "reason": str(exc)}

    # 6 — Manifest Google Doc (non-fatal)
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
    except Exception as exc:
        logger.warning("Manifest doc creation failed for client %r: %s", name, exc)

    logger.info(
        "Created client %r (id=%d) company=%r coaching_docs=%s client_type=%s",
        name, client_id, company_name, coaching_docs_url, new_type,
    )
    return {
        "status": "ok",
        "client_id": client_id,
        "name": name,
        "company_name": company_name,
        "client_type": new_type,
        "gdrive_coaching_docs_url": coaching_docs_url,
        "copied_files": [f["name"] for f in copied_files],
        "manifest_gdoc_url": manifest_gdoc_url,
        "obsidian": obsidian_result,
    }


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
    from connectors.drive import create_drive_folder
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
        projects_folder_id, _ = create_drive_folder("Projects", company_folder_id)
        project_folder_id, project_folder_url = create_drive_folder(name, projects_folder_id)
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
