"""Daily digest email — sent at 7:00 AM US/Eastern.

Builds and sends an HTML summary email covering:
  1. Today's sessions
  2. Tomorrow's sessions
  3. Note creation summary (run fresh)
  4. Granola sync rollup (accumulated via granola_daily_tally.json)
  5. Unprocessed completed meetings (past bananas, not confirmed)
  6. Sunday only — backup summary
"""

import base64
import email.policy
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAY_ABBR   = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

BACKUP_DASHY_DIR   = Path.home() / "Dropbox/2tech/Backups/dashy"
BACKUP_OBSIDIAN_DIR = Path.home() / "Dropbox/2tech/Backups/obsidian"


# ---------------------------------------------------------------------------
# Timezone helpers
# ---------------------------------------------------------------------------

def _eastern():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:
        try:
            import pytz
            return pytz.timezone("America/New_York")
        except Exception:
            return None


def _now_et() -> datetime:
    tz = _eastern()
    if tz is None:
        return datetime.now()
    return datetime.now(timezone.utc).astimezone(tz)


# ---------------------------------------------------------------------------
# Granola daily tally — accumulated across runs, read + reset by the digest
# ---------------------------------------------------------------------------

def _tally_path() -> Path:
    from config import DATA_DIR
    return Path(DATA_DIR) / "granola_daily_tally.json"


def accumulate_granola_tally(result: dict) -> None:
    """Called by sync.py after each granola_notes run to accumulate daily stats."""
    today = date.today().isoformat()
    path = _tally_path()
    try:
        tally = json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        tally = {}

    # Drop stale dates — keep only today
    tally = {k: v for k, v in tally.items() if k == today}
    entry = tally.get(today, {"fetched": 0, "matched": 0, "written": 0,
                               "skipped": 0, "unmatched": []})
    entry["fetched"]  += result.get("fetched", 0)
    entry["matched"]  += result.get("matched", 0)
    entry["written"]  += result.get("written", 0)
    entry["skipped"]  += result.get("skipped_existing", 0)
    # Merge unmatched titles (deduplicate)
    existing_unmatched = set(entry.get("unmatched", []))
    for title in result.get("unmatched", []):
        existing_unmatched.add(title)
    entry["unmatched"] = sorted(existing_unmatched)
    tally[today] = entry

    try:
        path.write_text(json.dumps(tally, indent=2))
    except Exception as exc:
        logger.warning("granola_daily_tally write failed: %s", exc)


def _read_and_reset_granola_tally() -> dict:
    """Read today's accumulated granola stats and clear the file."""
    today = date.today().isoformat()
    path = _tally_path()
    try:
        tally = json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        tally = {}
    entry = tally.get(today, {})
    # Clear today's entry so tomorrow starts fresh
    tally.pop(today, None)
    try:
        path.write_text(json.dumps(tally, indent=2))
    except Exception:
        pass
    return entry


# ---------------------------------------------------------------------------
# Data queries
# ---------------------------------------------------------------------------

def _format_time_12h(iso_str: str) -> str:
    """'2026-04-20T09:00:00-04:00' → '9:00am'"""
    try:
        dt = datetime.fromisoformat(iso_str)
        h, m = dt.hour, dt.minute
        suffix = "am" if h < 12 else "pm"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d}{suffix}"
    except Exception:
        return iso_str


def _get_sessions_for_date(db, target_date: date) -> list[dict]:
    """Return grape + banana calendar events for target_date, enriched with client/company/session#."""
    date_str = target_date.isoformat()
    rows = db.execute(
        """
        SELECT
            ce.id              AS ce_id,
            ce.start_time,
            ce.summary,
            ce.color_id,
            ce.attendees_json,
            bs.id              AS bs_id,
            bs.client_id,
            bs.project_id,
            bs.is_confirmed,
            bc.name            AS client_name,
            bc.company_id,
            bp.name            AS project_name,
            bp.company_id      AS bp_company_id,
            bco.name           AS company_name,
            (
                SELECT COALESCE(bs2.session_number,
                    (SELECT COUNT(*) FROM billing_sessions bs3
                     WHERE bs3.client_id = bs.client_id
                       AND bs3.is_confirmed = 1
                       AND bs3.date <= bs.date))
                FROM billing_sessions bs2
                WHERE bs2.id = bs.id
            ) AS session_number
        FROM calendar_events ce
        LEFT JOIN billing_sessions bs  ON bs.calendar_event_id = ce.id
        LEFT JOIN billing_clients  bc  ON bc.id = bs.client_id
        LEFT JOIN billing_projects bp  ON bp.id = bs.project_id
        LEFT JOIN billing_companies bco ON bco.id = COALESCE(bc.company_id, bp.company_id)
        WHERE ce.color_id IN ('3', '5')
          AND date(ce.start_time) = ?
          AND (ce.status IS NULL OR ce.status != 'cancelled')
        ORDER BY ce.start_time
        """,
        (date_str,),
    ).fetchall()

    out = []
    for r in rows:
        client = r["client_name"] or r["project_name"] or r["summary"] or "Unknown"
        company = r["company_name"] or ""
        out.append({
            "time": _format_time_12h(r["start_time"]),
            "client": client,
            "company": company,
            "session_number": r["session_number"],
            "color_id": r["color_id"],
        })
    return out


def _get_unprocessed_past_sessions(db) -> list[dict]:
    """Banana sessions (color_id='5') where date < today, is_confirmed=0, dismissed=0."""
    today_str = date.today().isoformat()
    rows = db.execute(
        """
        SELECT
            bs.date,
            bc.name  AS client_name,
            bp.name  AS project_name,
            bco.name AS company_name
        FROM billing_sessions bs
        LEFT JOIN billing_clients  bc  ON bc.id = bs.client_id
        LEFT JOIN billing_projects bp  ON bp.id = bs.project_id
        LEFT JOIN billing_companies bco ON bco.id = COALESCE(bc.company_id, bp.company_id)
        WHERE bs.color_id = '5'
          AND bs.date < ?
          AND bs.is_confirmed = 0
          AND bs.dismissed = 0
        ORDER BY bs.date DESC
        """,
        (today_str,),
    ).fetchall()

    out = []
    for r in rows:
        d = r["date"]
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            d = f"{DAY_ABBR[dt.weekday()]} {MONTH_ABBR[dt.month - 1]} {dt.day}"
        except Exception:
            pass
        client = r["client_name"] or r["project_name"] or "Unknown"
        out.append({"date": d, "client": client, "company": r["company_name"] or ""})
    return out


def _get_backup_summary() -> list[dict]:
    """Return most recent backup file from each backup dir."""
    results = []
    for label, directory in [("Dashy DB", BACKUP_DASHY_DIR), ("Obsidian Vault", BACKUP_OBSIDIAN_DIR)]:
        if not directory.exists():
            results.append({"label": label, "name": "—", "size": "—", "modified": "—"})
            continue
        files = sorted(
            [f for f in directory.iterdir() if f.is_file() and f.suffix == ".zip"],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not files:
            results.append({"label": label, "name": "(no zip files)", "size": "—", "modified": "—"})
            continue
        f = files[0]
        size_mb = f.stat().st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        results.append({
            "label": label,
            "name": f.name,
            "size": f"{size_mb:.1f} MB",
            "modified": mtime.strftime("%a %b %d %H:%M"),
        })
    return results


# ---------------------------------------------------------------------------
# Note creation
# ---------------------------------------------------------------------------

def _run_note_creation() -> dict:
    """Run create_upcoming_notes() and return its result dict."""
    try:
        from app_config import get_note_creation_config
        from connectors.note_creator import create_upcoming_notes

        cfg = get_note_creation_config()
        days_ahead = int(cfg.get("days_ahead", 5))
        return create_upcoming_notes(days_ahead=days_ahead)
    except Exception as exc:
        logger.warning("Note creation in daily digest failed: %s", exc)
        return {"daily_created": 0, "meeting_created": 0, "meeting_updated": 0,
                "skipped": 0, "log": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

_CSS = """
body { font-family: Georgia, serif; font-size: 14px; color: #222; max-width: 600px; margin: 0 auto; padding: 24px; }
h2 { font-size: 13px; font-variant: small-caps; letter-spacing: 0.08em; color: #888; margin: 24px 0 8px; text-transform: lowercase; }
hr { border: none; border-top: 1px solid #ddd; margin: 16px 0; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
td { padding: 3px 8px 3px 0; vertical-align: top; }
td.time { white-space: nowrap; color: #555; min-width: 60px; }
td.sno  { color: #999; font-size: 11px; white-space: nowrap; }
.none { color: #aaa; font-style: italic; font-size: 13px; }
.stat-row { display: flex; gap: 24px; font-size: 13px; margin-bottom: 6px; }
.stat-num  { font-weight: bold; }
.stat-label { color: #666; }
.unmatched { font-size: 12px; color: #b00; margin-top: 6px; }
.unmatched li { margin: 2px 0; }
.backup-row td { font-size: 12px; padding: 2px 8px 2px 0; }
""".strip()


def _session_rows_html(sessions: list[dict]) -> str:
    if not sessions:
        return '<p class="none">No sessions.</p>'
    rows = []
    for s in sessions:
        sno = f"#{s['session_number']}" if s["session_number"] else ""
        co = f" · {s['company']}" if s["company"] else ""
        rows.append(
            f"<tr>"
            f"<td class='time'>{s['time']}</td>"
            f"<td>{s['client']}{co}</td>"
            f"<td class='sno'>{sno}</td>"
            f"</tr>"
        )
    return f"<table>{''.join(rows)}</table>"


def _note_creation_html(result: dict) -> str:
    if "error" in result:
        return f'<p class="none">Note creation error: {result["error"]}</p>'

    daily = result.get("daily_created", 0)
    meeting_c = result.get("meeting_created", 0)
    meeting_u = result.get("meeting_updated", 0)
    skipped = result.get("skipped", 0)
    log = result.get("log", [])

    # Fix (3): · separated summary line
    dot = ' <span style="color:#ccc"> · </span> '
    skip_label = "skipped (already exist)" if skipped and daily == 0 and meeting_c == 0 else "skipped"
    stat_parts = [
        f'<span class="stat-num">{daily}</span> <span class="stat-label">daily notes</span>',
        f'<span class="stat-num">{meeting_c}</span> <span class="stat-label">meeting notes created</span>',
        f'<span class="stat-num">{meeting_u}</span> <span class="stat-label">updated</span>',
        f'<span class="stat-num">{skipped}</span> <span class="stat-label">{skip_label}</span>',
    ]
    lines = [f'<p style="font-size:13px;margin:0 0 6px">{dot.join(stat_parts)}</p>']

    # Fix (4): list created notes as  • YYYY-MM-DD — Client Name
    created = [e for e in log if e.get("status") == "created"]
    if created:
        items = []
        for e in created:
            stem = e.get("filename", "").replace(".md", "")
            if " - " in stem:
                date_part, name_part = stem.split(" - ", 1)
                items.append(f"<li style='font-size:12px;color:#555'>{date_part} &mdash; {name_part}</li>")
            else:
                items.append(f"<li style='font-size:12px;color:#555'>{stem}</li>")
        lines.append(f"<ul style='margin:4px 0 0 16px;padding:0'>{''.join(items)}</ul>")

    unmatched = [e for e in log if e.get("status") == "skipped" and "unmatched" in str(e.get("reason", ""))]
    if unmatched:
        items_html = "".join(f"<li>{e.get('filename','')}</li>" for e in unmatched)
        lines.append(f'<div class="unmatched"><strong>Unmatched events:</strong><ul>{items_html}</ul></div>')

    if not created and not unmatched and skipped == 0 and daily == 0 and meeting_c == 0:
        lines.append('<p class="none">All notes up to date — nothing to create.</p>')

    return "".join(lines)


def _granola_html(tally: dict) -> str:
    if not tally:
        return '<p class="none">No Granola syncs recorded since midnight.</p>'

    fetched  = tally.get("fetched", 0)
    matched  = tally.get("matched", 0)
    written  = tally.get("written", 0)
    skipped  = tally.get("skipped", 0)
    unmatched = tally.get("unmatched", [])

    lines = [
        f'<div class="stat-row">'
        f'<span><span class="stat-num">{fetched}</span> <span class="stat-label">fetched</span></span>'
        f'<span><span class="stat-num">{matched}</span> <span class="stat-label">matched</span></span>'
        f'<span><span class="stat-num">{written}</span> <span class="stat-label">written</span></span>'
        f'<span><span class="stat-num">{skipped}</span> <span class="stat-label">skipped</span></span>'
        f'</div>'
    ]
    if unmatched:
        items = "".join(f"<li>{title}</li>" for title in sorted(unmatched))
        lines.append(f'<div class="unmatched"><strong>Unmatched ({len(unmatched)}):</strong><ul>{items}</ul></div>')

    return "".join(lines)


def _unprocessed_html(sessions: list[dict]) -> str:
    if not sessions:
        return '<p class="none">All past sessions processed.</p>'
    rows = "".join(
        f"<tr><td class='time'>{s['date']}</td><td>{s['client']}"
        f"{'  ·  ' + s['company'] if s['company'] else ''}</td></tr>"
        for s in sessions
    )
    return f"<table>{rows}</table>"


def _backup_html(backups: list[dict]) -> str:
    rows = "".join(
        f"<tr class='backup-row'>"
        f"<td style='color:#555;width:110px'>{b['label']}</td>"
        f"<td>{b['name']}</td>"
        f"<td style='color:#888'>{b['size']}</td>"
        f"<td style='color:#aaa'>{b['modified']}</td>"
        f"</tr>"
        for b in backups
    )
    return f"<table>{rows}</table>"


def build_digest_html(
    today: date,
    tomorrow: date,
    today_sessions: list[dict],
    tomorrow_sessions: list[dict],
    note_result: dict,
    granola_tally: dict,
    unprocessed: list[dict],
    backups: list[dict] | None,
) -> str:
    is_sunday = today.weekday() == 6

    def _section(title: str, body: str) -> str:
        return f"<h2>{title}</h2>{body}"

    def _date_label(d: date) -> str:
        return f"{DAY_ABBR[d.weekday()]} {MONTH_ABBR[d.month - 1]} {d.day}"

    parts = [f"<html><head><style>{_CSS}</style></head><body>"]

    parts.append(_section(f"today's sessions — {_date_label(today)}", _session_rows_html(today_sessions)))
    parts.append("<hr>")
    parts.append(_section(f"tomorrow's sessions — {_date_label(tomorrow)}", _session_rows_html(tomorrow_sessions)))
    parts.append("<hr>")
    parts.append(_section("note creation", _note_creation_html(note_result)))
    parts.append("<hr>")
    parts.append(_section("granola sync — since midnight", _granola_html(granola_tally)))
    parts.append("<hr>")
    parts.append(_section("unprocessed past sessions", _unprocessed_html(unprocessed)))

    if is_sunday and backups is not None:
        parts.append("<hr>")
        parts.append(_section("backup summary", _backup_html(backups)))

    parts.append("</body></html>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Gmail send
# ---------------------------------------------------------------------------

def _get_gmail_service():
    """Build a Gmail API service using Google OAuth credentials."""
    from connectors.google_auth import get_google_credentials
    from googleapiclient.discovery import build

    creds = get_google_credentials()
    return build("gmail", "v1", credentials=creds)


def _build_html_mime(to: str, subject: str, html_body: str) -> str:
    """Build a base64url-encoded MIME message with an HTML body."""
    msg = EmailMessage(policy=email.policy.SMTP)
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(html_body, subtype="html")
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def send_daily_digest() -> dict:
    """Build and send the daily digest email. Returns a result dict."""
    from database import get_db_connection

    now_et = _now_et()
    today = now_et.date()
    tomorrow = today + timedelta(days=1)
    is_sunday = today.weekday() == 6

    # Subject line
    day_abbr = DAY_ABBR[today.weekday()]
    mon_abbr = MONTH_ABBR[today.month - 1]
    day_num  = today.day
    if is_sunday:
        subject = f"Dashy Weekly — {day_abbr} {mon_abbr} {day_num}"
    else:
        subject = f"Dashy Daily — {day_abbr} {mon_abbr} {day_num}"

    with get_db_connection(readonly=True) as db:
        today_sessions    = _get_sessions_for_date(db, today)
        tomorrow_sessions = _get_sessions_for_date(db, tomorrow)
        unprocessed       = _get_unprocessed_past_sessions(db)

    note_result   = _run_note_creation()
    granola_tally = _read_and_reset_granola_tally()
    backups       = _get_backup_summary() if is_sunday else None

    html = build_digest_html(
        today=today,
        tomorrow=tomorrow,
        today_sessions=today_sessions,
        tomorrow_sessions=tomorrow_sessions,
        note_result=note_result,
        granola_tally=granola_tally,
        unprocessed=unprocessed,
        backups=backups,
    )

    # Load recipient from dashy_install.json, fall back to profile
    to_addr = _resolve_digest_address()

    service = _get_gmail_service()
    raw = _build_html_mime(to_addr, subject, html)
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()

    logger.info("Daily digest sent to %s — subject: %s (msg id: %s)", to_addr, subject, result.get("id"))
    return {
        "sent": True,
        "subject": subject,
        "to": to_addr,
        "message_id": result.get("id"),
        "today_sessions": len(today_sessions),
        "tomorrow_sessions": len(tomorrow_sessions),
        "unprocessed": len(unprocessed),
    }


def _resolve_digest_address() -> str:
    """Read recipient from dashy_install.json, fall back to profile email."""
    try:
        install_path = Path(__file__).resolve().parent.parent.parent.parent / "dashy_install.json"
        if install_path.exists():
            data = json.loads(install_path.read_text())
            addr = data.get("user", {}).get("coach_email") or data.get("user", {}).get("email")
            if addr:
                return addr
    except Exception:
        pass
    try:
        from app_config import get_profile
        return get_profile().get("user_email", "")
    except Exception:
        return ""
