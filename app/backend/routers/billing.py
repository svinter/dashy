"""Billing module — Companies & Clients CRUD, session discovery/confirmation, seed import."""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db_connection, get_write_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])

SEED_PATH = Path(__file__).resolve().parent.parent / "dashy_billing_seed.json"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CompanyCreate(BaseModel):
    name: str
    abbrev: Optional[str] = None
    default_rate: Optional[float] = None
    billing_method: Optional[str] = None
    payment_method: Optional[str] = None
    payment_instructions: Optional[str] = None
    ap_email: Optional[str] = None
    cc_email: Optional[str] = None
    tax_tool: Optional[str] = None
    invoice_prefix: Optional[str] = None
    notes: Optional[str] = None
    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    active: bool = True


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    abbrev: Optional[str] = None
    default_rate: Optional[float] = None
    billing_method: Optional[str] = None
    payment_method: Optional[str] = None
    payment_instructions: Optional[str] = None
    ap_email: Optional[str] = None
    cc_email: Optional[str] = None
    tax_tool: Optional[str] = None
    invoice_prefix: Optional[str] = None
    notes: Optional[str] = None
    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    active: Optional[bool] = None


class ClientCreate(BaseModel):
    name: str
    company_id: int
    rate_override: Optional[float] = None
    prepaid: bool = False
    obsidian_name: Optional[str] = None
    employee_id: Optional[int] = None
    status: str = 'active'  # 'active' | 'infrequent' | 'inactive'


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    company_id: Optional[int] = None
    rate_override: Optional[float] = None
    prepaid: Optional[bool] = None
    obsidian_name: Optional[str] = None
    employee_id: Optional[int] = None
    status: Optional[str] = None  # 'active' | 'infrequent' | 'inactive'


class ProjectCreate(BaseModel):
    name: str
    company_id: int
    billing_type: str = "hourly"
    fixed_amount: Optional[float] = None
    rate_override: Optional[float] = None
    obsidian_name: Optional[str] = None
    gdrive_folder_url: Optional[str] = None
    gdrive_coaching_docs_url: Optional[str] = None
    active: bool = True


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    company_id: Optional[int] = None
    billing_type: Optional[str] = None
    fixed_amount: Optional[float] = None
    rate_override: Optional[float] = None
    obsidian_name: Optional[str] = None
    gdrive_folder_url: Optional[str] = None
    gdrive_coaching_docs_url: Optional[str] = None
    active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

COMPANY_COLS = {"name", "abbrev", "default_rate", "billing_method", "payment_method",
                "payment_instructions", "ap_email", "cc_email", "tax_tool",
                "invoice_prefix", "notes", "email_subject", "email_body", "active"}

CLIENT_COLS = {"name", "company_id", "rate_override", "prepaid", "obsidian_name",
               "employee_id", "status"}

PROJECT_COLS = {"name", "company_id", "billing_type", "fixed_amount", "rate_override",
                "obsidian_name", "gdrive_folder_url", "gdrive_coaching_docs_url", "active"}


def _row_to_dict(row) -> dict:
    return dict(row)


def _build_update(fields: dict, allowed: set) -> tuple[str, list]:
    """Build SET clause and params for an UPDATE, filtering to allowed columns."""
    pairs = [(k, v) for k, v in fields.items() if k in allowed]
    if not pairs:
        return "", []
    clause = ", ".join(f"{k} = ?" for k, _ in pairs)
    params = [v for _, v in pairs]
    return clause, params


# ---------------------------------------------------------------------------
# Billing settings (invoice output dir, provider info)
# ---------------------------------------------------------------------------

class BillingSettingsUpdate(BaseModel):
    invoice_output_dir: Optional[str] = None
    provider_name: Optional[str] = None
    provider_contact_name: Optional[str] = None
    provider_address1: Optional[str] = None
    provider_address2: Optional[str] = None
    provider_city_state_zip: Optional[str] = None
    provider_phone: Optional[str] = None
    provider_email: Optional[str] = None


PROVIDER_COLS = {
    "provider_name", "provider_contact_name", "provider_address1", "provider_address2",
    "provider_city_state_zip", "provider_phone", "provider_email",
}


def _get_provider_settings() -> dict:
    """Read provider contact info from billing_provider_settings (single row)."""
    with get_db_connection(readonly=True) as db:
        row = db.execute(
            "SELECT * FROM billing_provider_settings WHERE id = 1"
        ).fetchone()
    if row:
        return {c: row[c] or "" for c in PROVIDER_COLS}
    return {c: "" for c in PROVIDER_COLS}


def _update_provider_settings(fields: dict) -> None:
    """Write provider contact fields to the billing_provider_settings row."""
    filtered = {k: v for k, v in fields.items() if k in PROVIDER_COLS and v is not None}
    if not filtered:
        return
    clause = ", ".join(f"{k} = ?" for k in filtered)
    params = list(filtered.values())
    with get_write_db() as db:
        db.execute(
            f"UPDATE billing_provider_settings SET {clause} WHERE id = 1", params
        )
        db.commit()


@router.get("/settings")
def get_billing_settings_endpoint():
    from app_config import get_billing_settings
    return {**get_billing_settings(), **_get_provider_settings()}


@router.post("/settings")
def update_billing_settings_endpoint(body: BillingSettingsUpdate):
    from app_config import update_billing_settings
    data = body.model_dump(exclude_unset=True)
    config_fields = {k: v for k, v in data.items() if k not in PROVIDER_COLS and v is not None}
    provider_fields = {k: v for k, v in data.items() if k in PROVIDER_COLS}
    if config_fields:
        update_billing_settings(config_fields)
    if provider_fields:
        _update_provider_settings(provider_fields)
    from app_config import get_billing_settings
    return {**get_billing_settings(), **_get_provider_settings()}


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

@router.get("/companies")
def list_companies(active_only: bool = False):
    with get_db_connection(readonly=True) as db:
        q = "SELECT * FROM billing_companies"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY name"
        companies = [_row_to_dict(r) for r in db.execute(q).fetchall()]
        for co in companies:
            clients = db.execute(
                "SELECT * FROM billing_clients WHERE company_id = ? ORDER BY name",
                (co["id"],),
            ).fetchall()
            co["clients"] = [_row_to_dict(c) for c in clients]
    return companies


@router.post("/companies", status_code=201)
def create_company(body: CompanyCreate):
    with get_write_db() as db:
        cur = db.execute(
            """INSERT INTO billing_companies
               (name, abbrev, default_rate, billing_method, payment_method,
                ap_email, cc_email, tax_tool, invoice_prefix, notes, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.name, body.abbrev, body.default_rate, body.billing_method,
             body.payment_method, body.ap_email, body.cc_email, body.tax_tool,
             body.invoice_prefix, body.notes, int(body.active)),
        )
        db.commit()
        row = db.execute("SELECT * FROM billing_companies WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_dict(row)


@router.patch("/companies/{company_id}")
def update_company(company_id: int, body: CompanyUpdate):
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if "active" in fields and fields["active"] is not None:
        fields["active"] = int(fields["active"])
    clause, params = _build_update(fields, COMPANY_COLS)
    if not clause:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    params.append(company_id)
    with get_write_db() as db:
        db.execute(f"UPDATE billing_companies SET {clause} WHERE id = ?", params)
        db.commit()
        row = db.execute("SELECT * FROM billing_companies WHERE id = ?", (company_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Company not found")
    return _row_to_dict(row)


@router.delete("/companies/{company_id}")
def delete_company(company_id: int):
    with get_write_db() as db:
        db.execute("DELETE FROM billing_companies WHERE id = ?", (company_id,))
        db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

@router.get("/clients")
def list_clients(company_id: Optional[int] = None, active_only: bool = False):
    with get_db_connection(readonly=True) as db:
        q = "SELECT * FROM billing_clients WHERE 1=1"
        params: list = []
        if company_id is not None:
            q += " AND company_id = ?"
            params.append(company_id)
        if active_only:
            q += " AND status IN ('active', 'infrequent')"
        q += " ORDER BY name"
        rows = db.execute(q, params).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.post("/clients", status_code=201)
def create_client(body: ClientCreate):
    with get_write_db() as db:
        cur = db.execute(
            """INSERT INTO billing_clients
               (name, company_id, rate_override, prepaid, obsidian_name, employee_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (body.name, body.company_id, body.rate_override, int(body.prepaid),
             body.obsidian_name, body.employee_id, body.status),
        )
        db.commit()
        row = db.execute("SELECT * FROM billing_clients WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_dict(row)


@router.patch("/clients/{client_id}")
def update_client(client_id: int, body: ClientUpdate):
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if "prepaid" in fields and fields["prepaid"] is not None:
        fields["prepaid"] = int(fields["prepaid"])
    clause, params = _build_update(fields, CLIENT_COLS)
    if not clause:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    params.append(client_id)
    with get_write_db() as db:
        db.execute(f"UPDATE billing_clients SET {clause} WHERE id = ?", params)
        db.commit()
        row = db.execute("SELECT * FROM billing_clients WHERE id = ?", (client_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Client not found")
    return _row_to_dict(row)


@router.delete("/clients/{client_id}")
def delete_client(client_id: int):
    with get_write_db() as db:
        db.execute("DELETE FROM billing_clients WHERE id = ?", (client_id,))
        db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@router.get("/projects")
def list_projects(company_id: Optional[int] = None, active_only: bool = False):
    with get_db_connection(readonly=True) as db:
        q = "SELECT * FROM billing_projects WHERE 1=1"
        params: list = []
        if company_id is not None:
            q += " AND company_id = ?"
            params.append(company_id)
        if active_only:
            q += " AND active = 1"
        q += " ORDER BY name"
        rows = db.execute(q, params).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate):
    with get_write_db() as db:
        cur = db.execute(
            """INSERT INTO billing_projects
               (name, company_id, billing_type, fixed_amount, rate_override,
                obsidian_name, gdrive_folder_url, gdrive_coaching_docs_url, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.name, body.company_id, body.billing_type, body.fixed_amount,
             body.rate_override, body.obsidian_name, body.gdrive_folder_url,
             body.gdrive_coaching_docs_url, int(body.active)),
        )
        db.commit()
        row = db.execute("SELECT * FROM billing_projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_dict(row)


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectUpdate):
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if "active" in fields and fields["active"] is not None:
        fields["active"] = int(fields["active"])
    clause, params = _build_update(fields, PROJECT_COLS)
    if not clause:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    params.append(project_id)
    with get_write_db() as db:
        db.execute(f"UPDATE billing_projects SET {clause} WHERE id = ?", params)
        db.commit()
        row = db.execute("SELECT * FROM billing_projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
    return _row_to_dict(row)


@router.delete("/projects/{project_id}")
def delete_project(project_id: int):
    with get_write_db() as db:
        db.execute("DELETE FROM billing_projects WHERE id = ?", (project_id,))
        db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Seed import
# ---------------------------------------------------------------------------

@router.get("/seed/status")
def seed_status():
    with get_db_connection(readonly=True) as db:
        company_count = db.execute("SELECT COUNT(*) FROM billing_companies").fetchone()[0]
        client_count = db.execute("SELECT COUNT(*) FROM billing_clients").fetchone()[0]
        project_count = db.execute("SELECT COUNT(*) FROM billing_projects").fetchone()[0]
    return {
        "seeded": company_count > 0,
        "company_count": company_count,
        "client_count": client_count,
        "project_count": project_count,
        "seed_file_exists": SEED_PATH.exists(),
    }


@router.post("/seed/import")
def import_seed(force: bool = False):
    if not SEED_PATH.exists():
        raise HTTPException(status_code=404, detail=f"Seed file not found: {SEED_PATH}")

    # Parse JSON before touching the DB — fail fast with a clear message.
    try:
        seed = json.loads(SEED_PATH.read_text())
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"JSON syntax error: {exc}")

    companies_data = seed.get("companies", [])
    clients_data   = seed.get("clients", [])
    projects_data  = seed.get("projects", [])
    provider_data  = seed.get("provider", {})

    with get_db_connection(readonly=True) as db:
        existing = db.execute("SELECT COUNT(*) FROM billing_companies").fetchone()[0]
    if existing > 0 and not force:
        raise HTTPException(
            status_code=409,
            detail=f"Billing data already exists ({existing} companies). Delete all first or use force=true.",
        )

    # Build employee lookup before the write transaction (read-only, no lock needed).
    with get_db_connection(readonly=True) as db:
        emp_rows = db.execute("SELECT id, name FROM people").fetchall()
    emp_by_name = {r["name"].lower(): r["id"] for r in emp_rows}

    company_by_name: dict[str, int] = {}
    inserted_companies = 0
    inserted_clients = 0
    inserted_projects = 0
    relinked = 0

    # Single transaction: DELETE (if force) + all inserts.
    # get_write_db() rolls back automatically on any exception.
    try:
        with get_write_db() as db:
            if force and existing > 0:
                # Disable FK checks so we can clear master-data tables without
                # touching sessions, invoices, or payments.
                db.execute("PRAGMA foreign_keys=OFF")
                db.execute("DELETE FROM billing_projects")
                db.execute("DELETE FROM billing_clients")
                db.execute("DELETE FROM billing_companies")
                # Reset autoincrement sequences so re-imported rows get the same
                # IDs they had before, keeping billing_sessions FK references valid.
                db.execute("DELETE FROM sqlite_sequence WHERE name IN ('billing_projects', 'billing_clients', 'billing_companies')")
                db.execute("PRAGMA foreign_keys=ON")

            for co in companies_data:
                cur = db.execute(
                    """INSERT INTO billing_companies
                       (name, abbrev, default_rate, billing_method, payment_method,
                        ap_email, cc_email, tax_tool, invoice_prefix, notes, active)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        co["name"],
                        co.get("abbrev"),
                        co.get("default_rate"),
                        co.get("billing_method"),
                        co.get("payment_method"),
                        co.get("ap_email", ""),
                        co.get("cc_email", ""),
                        co.get("tax_tool"),
                        co.get("invoice_prefix"),
                        co.get("notes", ""),
                        int(co.get("active", True)),
                    ),
                )
                company_by_name[co["name"]] = cur.lastrowid
                inserted_companies += 1

            for cl in clients_data:
                company_name = cl.get("company", "")
                company_id = company_by_name.get(company_name)
                if company_id is None:
                    raise ValueError(f"Unknown company {company_name!r} for client {cl['name']!r}")

                db.execute(
                    """INSERT INTO billing_clients
                       (name, company_id, rate_override, prepaid, obsidian_name, employee_id, status,
                        client_type, gdrive_folder_url, gdrive_coaching_docs_url, email,
                        manifest_gdoc_url)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cl["name"],
                        company_id,
                        cl.get("rate_override"),
                        int(cl.get("prepaid", False)),
                        cl.get("obsidian_name", cl["name"]),
                        emp_by_name.get(cl["name"].lower()),
                        cl.get("status") or ("active" if cl.get("active", True) else "inactive"),
                        cl.get("client_type"),
                        cl.get("gdrive_folder_url") or None,
                        cl.get("gdrive_coaching_docs_url") or None,
                        cl.get("email") or None,
                        cl.get("manifest_gdoc_url") or None,
                    ),
                )
                inserted_clients += 1

            for pr in projects_data:
                company_name = pr.get("company", "")
                company_id = company_by_name.get(company_name)
                if company_id is None:
                    raise ValueError(f"Unknown company {company_name!r} for project {pr['name']!r}")

                db.execute(
                    """INSERT INTO billing_projects
                       (name, company_id, billing_type, fixed_amount, rate_override,
                        obsidian_name, gdrive_folder_url, gdrive_coaching_docs_url, active)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        pr["name"],
                        company_id,
                        pr.get("billing_type", "hourly"),
                        pr.get("fixed_amount"),
                        pr.get("rate_override"),
                        pr.get("obsidian_name", pr["name"]),
                        pr.get("gdrive_folder_url") or None,
                        pr.get("gdrive_coaching_docs_url") or None,
                        int(pr.get("active", True)),
                    ),
                )
                inserted_projects += 1

            db.commit()
            relinked = _relink_sessions_after_import(db)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Upsert provider settings from seed (outside the main transaction — safe to apply separately).
    if provider_data:
        _update_provider_settings({k: provider_data.get(k, "") for k in PROVIDER_COLS})

    return {
        "ok": True,
        "companies_imported": inserted_companies,
        "clients_imported": inserted_clients,
        "projects_imported": inserted_projects,
        "sessions_relinked": relinked,
        "provider_imported": bool(provider_data),
    }


# ---------------------------------------------------------------------------
# Session discovery helpers
# ---------------------------------------------------------------------------

def _slot_hours(start_time: str, end_time: str) -> float:
    """Return calendar slot duration rounded up to the nearest half hour.

    Examples: 25 min → 0.5, 30 min → 0.5, 55 min → 1.0, 75 min → 1.5
    """
    import math

    def _parse(s: str) -> datetime:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    try:
        raw = (_parse(end_time) - _parse(start_time)).total_seconds() / 3600
        return math.ceil(raw * 2) / 2
    except Exception:
        return 1.0


def _lookup_obsidian_note(date_str: str, obsidian_name: str) -> dict | None:
    """Try to find and parse an Obsidian meeting note for a given date and client name.

    Checks in order:
      1. 8 Meetings/YYYY-MM-DD - {obsidian_name}.md  (session note — preferred)
      2. 9 Daily/YYYY-MM-DD.md                        (daily note — fallback)

    Returns dict with keys: found, path, duration_hours, obsidian_link, duration_source.
    Returns None if the vault is not configured.
    """
    try:
        from connectors.obsidian import get_vault_path, get_vault_name, _parse_frontmatter
    except ImportError:
        return None

    vault = get_vault_path()
    if not vault:
        return None

    vault_name = get_vault_name() or ""

    def _make_link(rel: str) -> str:
        return f"obsidian://open?vault={quote(vault_name)}&file={quote(rel, safe='')}"

    def _parse_note(content: str) -> tuple[float | None, int | None]:
        """Return (duration_hours, session_number) from note frontmatter."""
        meta, _ = _parse_frontmatter(content)
        # Duration
        raw_dur = meta.get("duration")
        duration_hours = None
        if raw_dur:
            try:
                duration_hours = float(str(raw_dur).strip().strip('"').strip("'")) / 60
            except (ValueError, TypeError):
                pass
        # Session number from 'meeting' field
        raw_sn = meta.get("meeting")
        session_number = None
        if raw_sn is not None:
            try:
                session_number = int(str(raw_sn).strip())
            except (ValueError, TypeError):
                pass
        return duration_hours, session_number

    # 1. Session note in 8 Meetings/
    session_filename = f"{date_str} - {obsidian_name}.md"
    session_rel = f"8 Meetings/{session_filename}"
    session_path = vault / "8 Meetings" / session_filename

    if session_path.exists():
        try:
            duration_hours, session_number = _parse_note(session_path.read_text(encoding="utf-8", errors="replace"))
            return {
                "found": True,
                "path": session_rel,
                "duration_hours": round(duration_hours, 4) if duration_hours else None,
                "session_number": session_number,
                "obsidian_link": _make_link(session_rel),
                "duration_source": "obsidian" if duration_hours else "note_found_no_duration",
            }
        except Exception as e:
            logger.warning("Error reading obsidian session note %s: %s", session_path, e)

    # 2. Daily note fallback in 9 Daily/
    daily_rel = f"9 Daily/{date_str}.md"
    daily_path = vault / "9 Daily" / f"{date_str}.md"

    if daily_path.exists():
        try:
            duration_hours, session_number = _parse_note(daily_path.read_text(encoding="utf-8", errors="replace"))
            return {
                "found": True,
                "path": daily_rel,
                "duration_hours": round(duration_hours, 4) if duration_hours else None,
                "session_number": session_number,
                "obsidian_link": _make_link(daily_rel),
                "duration_source": "daily_note" if duration_hours else "daily_note_found_no_duration",
            }
        except Exception as e:
            logger.warning("Error reading obsidian daily note %s: %s", daily_path, e)

    # Neither found — return not-found with the session note as the intended target
    return {
        "found": False,
        "path": session_rel,
        "duration_hours": None,
        "session_number": None,
        "obsidian_link": _make_link(session_rel),
        "duration_source": None,
    }


def _get_user_email() -> str:
    """Return the user's own email from profile config, lowercased."""
    try:
        from app_config import load_config
        cfg = load_config()
        return cfg.get("profile", {}).get("user_email", "").lower()
    except Exception:
        return ""


def _get_user_name_parts() -> set[str]:
    """Return lowercased parts of the user's own name (to exclude from client title matching)."""
    try:
        from app_config import load_config
        cfg = load_config()
        name = cfg.get("profile", {}).get("user_name", "")
        if name:
            return {p.lower() for p in name.split() if p}
    except Exception:
        pass
    return set()


def _infer_client(summary: str, attendees_json: str, clients: list[dict]) -> tuple[int | None, str | None, float]:
    """Infer the most likely client from calendar event title and attendees.

    Returns (client_id, client_name, confidence) where confidence is 0.0–1.0.
    """
    summary_lower = summary.lower()
    user_email = _get_user_email()
    user_name_parts = _get_user_name_parts()

    # Parse attendees — exclude room resources and the user themselves
    all_attendees = []
    try:
        all_attendees = json.loads(attendees_json) if attendees_json else []
    except Exception:
        pass

    attendees = [
        a for a in all_attendees
        if a.get("email", "").lower() != user_email
        and not a.get("email", "").lower().endswith("@resource.calendar.google.com")
    ]

    attendee_names = [a.get("name", "").lower() for a in attendees if a.get("name")]
    attendee_emails = [a.get("email", "").lower() for a in attendees if a.get("email")]
    # Email local parts (before @) and dot-separated parts
    email_parts: set[str] = set()
    for email in attendee_emails:
        local = email.split("@")[0]
        email_parts.add(local)
        for part in re.split(r"[._]", local):
            if part:
                email_parts.add(part)

    best_id: int | None = None
    best_name: str | None = None
    best_score: float = 0.0

    for cl in clients:
        name: str = cl["name"]
        parts = name.split()
        first = parts[0].lower() if parts else ""
        last = parts[-1].lower() if len(parts) > 1 else ""
        name_lower = name.lower()
        score = 0.0

        # Skip matching on the user's own name parts — they appear in every event title
        if first in user_name_parts or (last and last in user_name_parts):
            pass  # don't score title matches for the user themselves
        else:
            # Full name in title
            if name_lower in summary_lower:
                score = max(score, 1.0)

            # Last name in title (word boundary)
            if last and re.search(r"\b" + re.escape(last) + r"\b", summary_lower):
                score = max(score, 0.75)

            # First name in title (word boundary)
            if first and re.search(r"\b" + re.escape(first) + r"\b", summary_lower):
                score = max(score, 0.55)

        # Attendee display name match
        for aname in attendee_names:
            if name_lower == aname:
                score = max(score, 0.95)
            elif first in aname or (last and last in aname):
                score = max(score, 0.70)

        # Email parts match
        if first and first in email_parts:
            score = max(score, 0.60)
        if last and last in email_parts:
            score = max(score, 0.65)
        # dot-separated full match e.g. "stacey.scott" in email
        for ep in email_parts:
            if first and last and f"{first}.{last}" == ep:
                score = max(score, 0.85)
            if first and last and f"{last}.{first}" == ep:
                score = max(score, 0.85)

        if score > best_score:
            best_score = score
            best_id = cl["id"]
            best_name = cl["name"]

    if best_score < 0.3:
        return None, None, 0.0

    return best_id, best_name, round(best_score, 2)


def _promote_banana_sessions(db) -> int:
    """Update billing_sessions where calendar event has since turned from banana→grape.

    Returns count of sessions promoted.
    """
    rows = db.execute("""
        SELECT bs.id, bs.calendar_event_id, ce.start_time, bc.obsidian_name,
               bs.rate, bs.client_id
        FROM billing_sessions bs
        JOIN calendar_events ce ON ce.id = bs.calendar_event_id
        LEFT JOIN billing_clients bc ON bc.id = bs.client_id
        WHERE bs.color_id = '5' AND ce.color_id = '3' AND bs.dismissed = 0
    """).fetchall()

    promoted = 0
    for row in rows:
        date_str = row["start_time"][:10]
        note_info = _lookup_obsidian_note(date_str, row["obsidian_name"])
        update_parts = ["color_id = '3'", "is_confirmed = 1"]
        params: list = []
        if note_info and note_info.get("duration_hours"):
            dh = note_info["duration_hours"]
            amt = round(dh * (row["rate"] or 0), 2)
            update_parts += ["duration_hours = ?", "amount = ?",
                              "obsidian_note_path = ?"]
            params += [dh, amt, note_info["path"]]
        if note_info and note_info.get("session_number") is not None:
            update_parts.append("session_number = ?")
            params.append(note_info["session_number"])
        params.append(row["id"])
        db.execute(
            f"UPDATE billing_sessions SET {', '.join(update_parts)} WHERE id = ?",
            params,
        )
        promoted += 1

    if promoted:
        db.commit()
    return promoted


def _relink_sessions_after_import(db) -> int:
    """Re-link billing_sessions.client_id after a seed re-import, and re-apply rates.

    Matches obsidian_note_path (format '8 Meetings/YYYY-MM-DD - {name}.md')
    to billing_clients.obsidian_name (or name) to restore FK references that
    become stale when billing_clients rows are deleted and re-inserted with
    new autoincrement IDs.  Also re-applies the effective rate (client
    rate_override if set, otherwise company default_rate) to any session whose
    stored rate no longer matches, recalculating amount accordingly.

    Returns count of sessions updated.
    """
    # Build lookup maps keyed by normalised name
    clients = db.execute(
        "SELECT bc.id, bc.name, bc.obsidian_name, bc.company_id, bc.rate_override, "
        "bco.default_rate "
        "FROM billing_clients bc "
        "JOIN billing_companies bco ON bco.id = bc.company_id"
    ).fetchall()

    # (client_id, company_id, effective_rate)
    by_obsidian: dict[str, tuple[int, int, float | None]] = {}
    by_name: dict[str, tuple[int, int, float | None]] = {}
    for cl in clients:
        eff_rate = cl["rate_override"] if cl["rate_override"] is not None else cl["default_rate"]
        val = (cl["id"], cl["company_id"], eff_rate)
        obs = (cl["obsidian_name"] or cl["name"]).lower().strip()
        by_obsidian[obs] = val
        by_name[cl["name"].lower().strip()] = val

    sessions = db.execute(
        "SELECT id, client_id, company_id, rate, duration_hours, obsidian_note_path "
        "FROM billing_sessions WHERE dismissed = 0"
    ).fetchall()

    updated = 0
    for sess in sessions:
        path = sess["obsidian_note_path"]
        match: tuple[int, int, float | None] | None = None

        if path:
            dash_pos = path.find(" - ")
            if dash_pos != -1:
                name_part = path[dash_pos + 3:]
                if name_part.endswith(".md"):
                    name_part = name_part[:-3]
                name_key = name_part.lower().strip()
                match = by_obsidian.get(name_key) or by_name.get(name_key)

        if match:
            new_client_id, new_company_id, eff_rate = match
        elif sess["company_id"] is not None:
            # No path match — still re-apply rate if company default changed
            company_rate = db.execute(
                "SELECT default_rate FROM billing_companies WHERE id = ?",
                (sess["company_id"],),
            ).fetchone()
            if company_rate is None:
                continue
            eff_rate = company_rate["default_rate"]
            new_client_id = sess["client_id"]
            new_company_id = sess["company_id"]
        else:
            continue

        need_relink = (new_client_id != sess["client_id"])
        need_rerate = (eff_rate is not None and eff_rate != sess["rate"])

        if not need_relink and not need_rerate:
            continue

        new_rate = eff_rate if need_rerate else sess["rate"]
        new_amount = round(sess["duration_hours"] * new_rate, 2) if need_rerate else None
        update_sql = "UPDATE billing_sessions SET client_id = ?, company_id = ?, rate = ?"
        params: list = [new_client_id, new_company_id, new_rate]
        if new_amount is not None:
            update_sql += ", amount = ?"
            params.append(new_amount)
        update_sql += " WHERE id = ?"
        params.append(sess["id"])
        db.execute(update_sql, params)
        updated += 1

    if updated:
        db.commit()
    return updated


def _session_to_dict(row) -> dict:
    d = dict(row)
    d["is_confirmed"] = bool(d.get("is_confirmed"))
    d["dismissed"] = bool(d.get("dismissed"))
    d["prepaid"] = bool(d.get("prepaid"))
    d["canceled"] = bool(d.get("canceled"))
    # Compute obsidian_link from stored path if available
    path = d.get("obsidian_note_path")
    if path:
        try:
            from connectors.obsidian import get_vault_name
            vault_name = get_vault_name() or ""
            encoded_rel = quote(path, safe="")
            d["obsidian_link"] = f"obsidian://open?vault={quote(vault_name)}&file={encoded_rel}"
        except Exception:
            d["obsidian_link"] = None
    else:
        d["obsidian_link"] = None
    return d


# ---------------------------------------------------------------------------
# Session Pydantic models
# ---------------------------------------------------------------------------

class SessionConfirm(BaseModel):
    calendar_event_id: str
    client_id: Optional[int] = None    # null for "no specific client"
    company_id: Optional[int] = None   # required when client_id and project_id are null
    project_id: Optional[int] = None   # alternative to client_id — session belongs to a project
    duration_hours: float
    notes: Optional[str] = None        # used as invoice description when no client


class SessionDismiss(BaseModel):
    calendar_event_id: str


class SessionUpdate(BaseModel):
    client_id: Optional[int] = None
    company_id: Optional[int] = None
    date: Optional[str] = None
    duration_hours: Optional[float] = None
    rate: Optional[float] = None
    amount: Optional[float] = None
    notes: Optional[str] = None
    obsidian_note_path: Optional[str] = None
    is_confirmed: Optional[bool] = None
    dismissed: Optional[bool] = None
    session_number: Optional[int] = None


class SessionCreate(BaseModel):
    date: str                           # YYYY-MM-DD
    client_id: Optional[int] = None
    company_id: Optional[int] = None    # required when client_id is null
    duration_hours: float
    rate: Optional[float] = None        # overrides client/company rate if provided
    notes: Optional[str] = None
    is_confirmed: bool = True


SESSION_ALLOWED = {"client_id", "project_id", "company_id", "date", "duration_hours", "rate",
                   "amount", "notes", "obsidian_note_path", "is_confirmed", "dismissed",
                   "prepaid_block_id", "session_number"}


# ---------------------------------------------------------------------------
# Badge counts — lightweight endpoint for sidebar indicators
# ---------------------------------------------------------------------------

@router.get("/badge-counts")
def get_badge_counts():
    """Return queue and unmatched-payment counts for sidebar badges."""
    with get_db_connection(readonly=True) as db:
        queue_count = db.execute(
            """SELECT COUNT(*) as c FROM calendar_events
               WHERE color_id IN ('3', '5')
               AND date(start_time) < date('now', 'localtime')
               AND id NOT IN (
                   SELECT calendar_event_id FROM billing_sessions
                   WHERE calendar_event_id IS NOT NULL
                   AND (dismissed = 1 OR is_confirmed = 1)
               )"""
        ).fetchone()["c"]

        unmatched_payments_count = db.execute(
            """SELECT COUNT(*) as c FROM billing_payments
               WHERE company_id IS NOT NULL
               AND strftime('%Y-%m', date) = strftime('%Y-%m', 'now')
               AND NOT EXISTS (
                   SELECT 1 FROM billing_invoice_payments WHERE payment_id = billing_payments.id
               )"""
        ).fetchone()["c"]

    return {"queue_count": queue_count, "unmatched_payments_count": unmatched_payments_count}


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------

@router.get("/sessions/unprocessed")
def get_unprocessed_sessions():
    """Return calendar events with color_id 3 or 5 not yet in billing_sessions,
    with client inference and Obsidian note lookup for each.
    Also triggers banana→grape promotion for existing sessions.
    """
    with get_db_connection(readonly=True) as db:
        # Get all clients with company info for inference
        clients = [dict(r) for r in db.execute(
            "SELECT bc.*, bco.default_rate FROM billing_clients bc "
            "JOIN billing_companies bco ON bco.id = bc.company_id "
            "WHERE bc.status IN ('active', 'infrequent')"
        ).fetchall()]

        # IDs already handled: dismissed stubs OR confirmed sessions.
        # Unconfirmed sessions (is_confirmed=0, dismissed=0) are re-shown in Queue
        # so they can be confirmed from either view.
        existing_ids = {
            r[0] for r in db.execute(
                "SELECT calendar_event_id FROM billing_sessions "
                "WHERE calendar_event_id IS NOT NULL AND (dismissed = 1 OR is_confirmed = 1)"
            ).fetchall()
        }

        events = db.execute("""
            SELECT id, summary, start_time, end_time, attendees_json, color_id
            FROM calendar_events
            WHERE color_id IN ('3', '5')
            ORDER BY start_time DESC
        """).fetchall()

    # Promote banana→grape in a write connection
    with get_write_db() as wdb:
        promoted = _promote_banana_sessions(wdb)
    if promoted:
        logger.info("Promoted %d banana→grape sessions", promoted)

    now_utc = datetime.now(timezone.utc)

    def _is_active(start_raw: str, end_raw: str) -> bool:
        """True when start_time <= now(UTC) <= end_time (timezone-aware comparison)."""
        try:
            start = datetime.fromisoformat(start_raw)
            end   = datetime.fromisoformat(end_raw)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end   = end.replace(tzinfo=timezone.utc)
            return start.astimezone(timezone.utc) <= now_utc <= end.astimezone(timezone.utc)
        except (ValueError, TypeError):
            return False

    result = []
    for ev in events:
        if ev["id"] in existing_ids:
            continue

        slot_hrs = round(_slot_hours(ev["start_time"], ev["end_time"]), 4)
        is_grape = ev["color_id"] == "3"
        date_str = ev["start_time"][:10]

        # Client inference
        client_id, client_name, confidence = _infer_client(
            ev["summary"] or "", ev["attendees_json"] or "[]", clients
        )

        # Obsidian note lookup (only when we have a client)
        obsidian: dict | None = None
        if client_id and is_grape:
            cl = next((c for c in clients if c["id"] == client_id), None)
            if cl:
                obsidian = _lookup_obsidian_note(date_str, cl["obsidian_name"] or cl["name"])

        # Best duration estimate
        if obsidian and obsidian.get("duration_hours"):
            duration_hours = obsidian["duration_hours"]
            duration_source = "obsidian"
        else:
            duration_hours = slot_hrs
            duration_source = "calendar_slot"

        # Resolve inferred company_id from inferred client
        inferred_company_id: int | None = None
        if client_id:
            cl_row = next((c for c in clients if c["id"] == client_id), None)
            if cl_row:
                inferred_company_id = cl_row.get("company_id")

        result.append({
            "calendar_event_id": ev["id"],
            "summary": ev["summary"],
            "start_time": ev["start_time"],
            "end_time": ev["end_time"],
            "color_id": ev["color_id"],
            "is_grape": is_grape,
            "is_active": _is_active(ev["start_time"], ev["end_time"]),
            "slot_hours": slot_hrs,
            "duration_hours": duration_hours,
            "duration_source": duration_source,
            "inferred_client_id": client_id,
            "inferred_client_name": client_name,
            "inferred_company_id": inferred_company_id,
            "inferred_confidence": confidence,
            "obsidian": obsidian,
        })

    return {"events": result, "count": len(result)}


@router.post("/sessions/confirm", status_code=201)
def confirm_session(body: SessionConfirm):
    """Confirm an unprocessed calendar event as a billing session.

    Two modes:
      - client_id set: normal path — looks up client for rate/obsidian_name/company
      - client_id null + company_id set: company-only session; notes used as description
    """
    if not body.client_id and not body.project_id and not body.company_id:
        raise HTTPException(status_code=422, detail="Either client_id, project_id, or company_id is required")

    with get_write_db() as db:
        ev = db.execute(
            "SELECT start_time, end_time, color_id FROM calendar_events WHERE id = ?",
            (body.calendar_event_id,)
        ).fetchone()
        if not ev:
            raise HTTPException(status_code=404, detail="Calendar event not found")

        is_confirmed = True
        date_str = ev["start_time"][:10]
        is_prepaid = False
        note_path = None
        project_id_to_save = None

        if body.client_id:
            # Normal client path
            cl = db.execute(
                "SELECT bc.*, bco.default_rate, bco.id as co_id "
                "FROM billing_clients bc JOIN billing_companies bco ON bco.id = bc.company_id "
                "WHERE bc.id = ?", (body.client_id,)
            ).fetchone()
            if not cl:
                raise HTTPException(status_code=404, detail="Client not found")

            rate = cl["rate_override"] if cl["rate_override"] is not None else cl["default_rate"]
            is_prepaid = bool(cl["prepaid"])
            amount = 0.0 if is_prepaid else round(body.duration_hours * (rate or 0), 2)
            company_id = cl["co_id"]

            obsidian_name = cl["obsidian_name"] or cl["name"]
            note_info = _lookup_obsidian_note(date_str, obsidian_name)
            note_path = note_info["path"] if note_info else f"8 Meetings/{date_str} - {obsidian_name}.md"

        elif body.project_id:
            # Project path: session belongs to a project, not a specific client
            pr = db.execute(
                "SELECT bp.*, bco.default_rate, bco.id as co_id "
                "FROM billing_projects bp JOIN billing_companies bco ON bco.id = bp.company_id "
                "WHERE bp.id = ?", (body.project_id,)
            ).fetchone()
            if not pr:
                raise HTTPException(status_code=404, detail="Project not found")

            if pr["billing_type"] == "fixed":
                # Fixed-rate: session records hours but $0 (billed separately)
                rate = None
                amount = 0.0
            else:
                rate = pr["rate_override"] if pr["rate_override"] is not None else pr["default_rate"]
                amount = round(body.duration_hours * (rate or 0), 2)

            company_id = pr["co_id"]
            project_id_to_save = body.project_id

            obsidian_name = pr["obsidian_name"] or pr["name"]
            note_info = _lookup_obsidian_note(date_str, obsidian_name)
            note_path = note_info["path"] if note_info else f"8 Meetings/{date_str} - {obsidian_name}.md"

        else:
            # Company-only path: no client, no project
            co = db.execute(
                "SELECT * FROM billing_companies WHERE id = ?", (body.company_id,)
            ).fetchone()
            if not co:
                raise HTTPException(status_code=404, detail="Company not found")

            rate = co["default_rate"]
            amount = round(body.duration_hours * (rate or 0), 2)
            company_id = body.company_id

        # If an unconfirmed session already exists for this calendar event, UPDATE it
        existing = db.execute(
            "SELECT id FROM billing_sessions WHERE calendar_event_id = ? AND dismissed = 0",
            (body.calendar_event_id,)
        ).fetchone()

        if existing:
            db.execute(
                """UPDATE billing_sessions SET
                   client_id=?, project_id=?, company_id=?, duration_hours=?, rate=?, amount=?,
                   is_confirmed=?, color_id=?, obsidian_note_path=?, notes=?
                   WHERE id=?""",
                (body.client_id, project_id_to_save, company_id, body.duration_hours, rate, amount,
                 int(is_confirmed), ev["color_id"],
                 note_path if (body.client_id or project_id_to_save) else None,
                 body.notes or "", existing["id"]),
            )
            session_id = existing["id"]
        else:
            cur = db.execute(
                """INSERT INTO billing_sessions
                   (date, client_id, project_id, company_id, duration_hours, rate, amount,
                    is_confirmed, calendar_event_id, color_id, obsidian_note_path, notes, dismissed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (date_str, body.client_id, project_id_to_save, company_id, body.duration_hours,
                 rate, amount, int(is_confirmed), body.calendar_event_id,
                 ev["color_id"],
                 note_path if (body.client_id or project_id_to_save) else None,
                 body.notes or ""),
            )
            session_id = cur.lastrowid

        # Auto-link to active prepaid block when client is prepaid
        no_active_prepaid_block = False
        if is_prepaid and body.client_id:
            active_block = db.execute(
                """SELECT pb.id, pb.hours_purchased,
                          COALESCE(SUM(bs2.duration_hours), 0) AS hours_used
                   FROM billing_prepaid_blocks pb
                   LEFT JOIN billing_sessions bs2
                          ON bs2.prepaid_block_id = pb.id
                         AND bs2.dismissed = 0
                         AND bs2.id != ?
                   WHERE pb.client_id = ?
                     AND pb.hours_purchased IS NOT NULL
                     AND (pb.starting_after_date IS NULL OR pb.starting_after_date <= ?)
                   GROUP BY pb.id
                   HAVING hours_used < pb.hours_purchased
                   ORDER BY pb.starting_after_date ASC
                   LIMIT 1""",
                (session_id, body.client_id, date_str),
            ).fetchone()
            if active_block:
                db.execute(
                    "UPDATE billing_sessions SET prepaid_block_id = ? WHERE id = ?",
                    (active_block["id"], session_id),
                )
            else:
                no_active_prepaid_block = True

        db.commit()
        row = db.execute(
            """SELECT bs.*, bc.name as client_name, bc.prepaid, bco.name as company_name,
                      bco.abbrev as company_abbrev, bp.name as project_name
               FROM billing_sessions bs
               LEFT JOIN billing_clients bc ON bc.id = bs.client_id
               LEFT JOIN billing_companies bco ON bco.id = bs.company_id
               LEFT JOIN billing_projects bp ON bp.id = bs.project_id
               WHERE bs.id = ?""", (session_id,)
        ).fetchone()

    result = _session_to_dict(row)
    if no_active_prepaid_block:
        result["no_active_prepaid_block"] = True
    return result


# ---------------------------------------------------------------------------
# Confirm past banana: update GCal colorId → grape, then confirm session
# ---------------------------------------------------------------------------

_CALENDAR_WRITE_SCOPES = {
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
}


def _has_calendar_write_scope() -> bool:
    """Return True if the stored Google token includes a calendar write scope."""
    from connectors.google_auth import TOKEN_PATH

    if not TOKEN_PATH.exists():
        return False
    try:
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
        if not creds.scopes:
            return True  # scopes not in token — assume sufficient (ADC path)
        return bool(_CALENDAR_WRITE_SCOPES.intersection(set(creds.scopes)))
    except Exception:
        return False


@router.post("/sessions/confirm-past-banana", status_code=201)
def confirm_past_banana(body: SessionConfirm):
    """Confirm a past banana event: set GCal colorId→grape, then confirm session.

    Returns {"need_reauth": true} if the token lacks calendar write scope.
    All four steps (GCal update, local calendar_events update, session upsert,
    prepaid block link) execute as a unit.
    """
    if not body.client_id and not body.company_id:
        raise HTTPException(status_code=422, detail="Either client_id or company_id is required")

    # Step 1 — scope check
    if not _has_calendar_write_scope():
        return {"need_reauth": True}

    # Step 2 — update Google Calendar colorId to grape (3)
    try:
        from googleapiclient.discovery import build
        from connectors.google_auth import get_google_credentials

        creds = get_google_credentials()
        service = build("calendar", "v3", credentials=creds)
        service.events().patch(
            calendarId="primary",
            eventId=body.calendar_event_id,
            body={"colorId": "3"},
        ).execute()
        logger.info("confirm_past_banana: updated GCal event %s colorId → grape", body.calendar_event_id)
    except Exception as e:
        logger.error("confirm_past_banana: GCal update failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to update Google Calendar: {e}")

    # Steps 3+4 — update local DB and confirm session (same logic as confirm_session
    # but forces color_id='3' regardless of the stored calendar_events value)
    with get_write_db() as db:
        # Update local calendar_events so the queue no longer treats it as banana
        db.execute(
            "UPDATE calendar_events SET color_id = '3' WHERE id = ?",
            (body.calendar_event_id,),
        )

        ev = db.execute(
            "SELECT start_time, end_time, color_id FROM calendar_events WHERE id = ?",
            (body.calendar_event_id,),
        ).fetchone()
        if not ev:
            raise HTTPException(status_code=404, detail="Calendar event not found")

        date_str = ev["start_time"][:10]
        is_prepaid = False
        note_path = None

        if body.client_id:
            cl = db.execute(
                "SELECT bc.*, bco.default_rate, bco.id as co_id "
                "FROM billing_clients bc JOIN billing_companies bco ON bco.id = bc.company_id "
                "WHERE bc.id = ?",
                (body.client_id,),
            ).fetchone()
            if not cl:
                raise HTTPException(status_code=404, detail="Client not found")

            rate = cl["rate_override"] if cl["rate_override"] is not None else cl["default_rate"]
            is_prepaid = bool(cl["prepaid"])
            amount = 0.0 if is_prepaid else round(body.duration_hours * (rate or 0), 2)
            company_id = cl["co_id"]

            obsidian_name = cl["obsidian_name"] or cl["name"]
            note_info = _lookup_obsidian_note(date_str, obsidian_name)
            note_path = note_info["path"] if note_info else f"8 Meetings/{date_str} - {obsidian_name}.md"
        else:
            co = db.execute(
                "SELECT * FROM billing_companies WHERE id = ?", (body.company_id,)
            ).fetchone()
            if not co:
                raise HTTPException(status_code=404, detail="Company not found")

            rate = co["default_rate"]
            amount = round(body.duration_hours * (rate or 0), 2)
            company_id = body.company_id

        existing = db.execute(
            "SELECT id FROM billing_sessions WHERE calendar_event_id = ? AND dismissed = 0",
            (body.calendar_event_id,),
        ).fetchone()

        if existing:
            db.execute(
                """UPDATE billing_sessions SET
                   client_id=?, company_id=?, duration_hours=?, rate=?, amount=?,
                   is_confirmed=1, color_id='3', obsidian_note_path=?, notes=?
                   WHERE id=?""",
                (body.client_id, company_id, body.duration_hours, rate, amount,
                 note_path if body.client_id else None,
                 body.notes or "", existing["id"]),
            )
            session_id = existing["id"]
        else:
            cur = db.execute(
                """INSERT INTO billing_sessions
                   (date, client_id, company_id, duration_hours, rate, amount,
                    is_confirmed, calendar_event_id, color_id, obsidian_note_path, notes, dismissed)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?, '3', ?, ?, 0)""",
                (date_str, body.client_id, company_id, body.duration_hours,
                 rate, amount, body.calendar_event_id,
                 note_path if body.client_id else None, body.notes or ""),
            )
            session_id = cur.lastrowid

        no_active_prepaid_block = False
        if is_prepaid and body.client_id:
            active_block = db.execute(
                """SELECT pb.id, pb.hours_purchased,
                          COALESCE(SUM(bs2.duration_hours), 0) AS hours_used
                   FROM billing_prepaid_blocks pb
                   LEFT JOIN billing_sessions bs2
                          ON bs2.prepaid_block_id = pb.id
                         AND bs2.dismissed = 0
                         AND bs2.id != ?
                   WHERE pb.client_id = ?
                     AND pb.hours_purchased IS NOT NULL
                     AND (pb.starting_after_date IS NULL OR pb.starting_after_date <= ?)
                   GROUP BY pb.id
                   HAVING hours_used < pb.hours_purchased
                   ORDER BY pb.starting_after_date ASC
                   LIMIT 1""",
                (session_id, body.client_id, date_str),
            ).fetchone()
            if active_block:
                db.execute(
                    "UPDATE billing_sessions SET prepaid_block_id = ? WHERE id = ?",
                    (active_block["id"], session_id),
                )
            else:
                no_active_prepaid_block = True

        db.commit()
        row = db.execute(
            "SELECT bs.*, bc.name as client_name, bc.prepaid, bco.name as company_name, bco.abbrev as company_abbrev "
            "FROM billing_sessions bs "
            "LEFT JOIN billing_clients bc ON bc.id = bs.client_id "
            "LEFT JOIN billing_companies bco ON bco.id = bs.company_id "
            "WHERE bs.id = ?",
            (session_id,),
        ).fetchone()

    result = _session_to_dict(row)
    if no_active_prepaid_block:
        result["no_active_prepaid_block"] = True
    return result


@router.post("/sessions/dismiss")
def dismiss_session(body: SessionDismiss):
    """Mark a calendar event as dismissed — removes it from the unprocessed queue."""
    with get_write_db() as db:
        ev = db.execute(
            "SELECT start_time, color_id FROM calendar_events WHERE id = ?",
            (body.calendar_event_id,)
        ).fetchone()
        if not ev:
            raise HTTPException(status_code=404, detail="Calendar event not found")

        existing = db.execute(
            "SELECT id FROM billing_sessions WHERE calendar_event_id = ?",
            (body.calendar_event_id,)
        ).fetchone()
        if existing:
            db.execute("UPDATE billing_sessions SET dismissed=1 WHERE id=?", (existing["id"],))
        else:
            # Insert a stub session with dismissed=1 to remove from queue
            db.execute(
                """INSERT INTO billing_sessions
                   (date, calendar_event_id, color_id, dismissed,
                    is_confirmed, duration_hours, rate, amount)
                   VALUES (?, ?, ?, 1, 0, 0, 0, 0)""",
                (ev["start_time"][:10], body.calendar_event_id, ev["color_id"]),
            )
        db.commit()
    return {"ok": True}


@router.get("/sessions/dismissed")
def list_dismissed_sessions():
    """Return dismissed billing sessions (stubs and real) with calendar event info."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute("""
            SELECT bs.id,
                   bs.calendar_event_id,
                   bs.date,
                   bs.color_id,
                   bs.duration_hours,
                   bs.is_confirmed,
                   bs.created_at,
                   ce.summary,
                   ce.start_time,
                   ce.end_time,
                   bc.name  AS client_name,
                   bco.name AS company_name
            FROM billing_sessions bs
            LEFT JOIN calendar_events ce ON ce.id = bs.calendar_event_id
            LEFT JOIN billing_clients bc ON bc.id = bs.client_id
            LEFT JOIN billing_companies bco ON bco.id = bs.company_id
            WHERE bs.dismissed = 1
            ORDER BY bs.date DESC, bs.id DESC
        """).fetchall()
    return [dict(r) for r in rows]


@router.get("/sessions")
def list_sessions(
    company_id: Optional[int] = None,
    client_id: Optional[int] = None,
    month: Optional[str] = None,  # YYYY-MM
    confirmed_only: bool = False,
    unconfirmed_only: bool = False,
    show_canceled: bool = False,
):
    """Return confirmed (non-dismissed) billing sessions with client/company info."""
    with get_db_connection(readonly=True) as db:
        q = """
            WITH sno AS (
                SELECT id,
                       ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY date, id) AS rn
                FROM billing_sessions
                WHERE client_id IS NOT NULL AND dismissed = 0 AND is_confirmed = 1
            ),
            latest_blocks AS (
                -- Most recently created block per client (by id)
                SELECT client_id, starting_after_date
                FROM billing_prepaid_blocks
                WHERE id IN (SELECT MAX(id) FROM billing_prepaid_blocks GROUP BY client_id)
            ),
            block_cum AS (
                -- Running cumulative hours within each client's active block period
                SELECT bs2.id,
                       SUM(bs2.duration_hours) OVER (
                           PARTITION BY bs2.client_id
                           ORDER BY bs2.date, bs2.id
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                       ) AS cumulative_block_hours
                FROM billing_sessions bs2
                JOIN latest_blocks lb ON lb.client_id = bs2.client_id
                WHERE bs2.dismissed = 0 AND bs2.is_confirmed = 1
                  AND (lb.starting_after_date IS NULL OR bs2.date > lb.starting_after_date)
            )
            SELECT bs.*,
                   bc.name  AS client_name,
                   bc.prepaid AS prepaid,
                   bco.name AS company_name,
                   bco.abbrev AS company_abbrev,
                   bp.name  AS project_name,
                   bil.invoice_id AS invoice_id,
                   COALESCE(bs.session_number, sno.rn) AS display_session_number,
                   block_cum.cumulative_block_hours
            FROM billing_sessions bs
            LEFT JOIN billing_clients bc  ON bc.id  = bs.client_id
            LEFT JOIN billing_companies bco ON bco.id = bs.company_id
            LEFT JOIN billing_projects bp ON bp.id = bs.project_id
            LEFT JOIN billing_invoice_lines bil ON bil.id = bs.invoice_line_id
            LEFT JOIN sno ON sno.id = bs.id
            LEFT JOIN block_cum ON block_cum.id = bs.id
            WHERE bs.dismissed = 0 AND bs.is_confirmed = 1
        """
        params: list = []
        if company_id:
            q += " AND bs.company_id = ?"
            params.append(company_id)
        if client_id:
            q += " AND bs.client_id = ?"
            params.append(client_id)
        if month:
            q += " AND bs.date LIKE ?"
            params.append(f"{month}%")
        if confirmed_only:
            q += " AND bs.is_confirmed = 1"
        if unconfirmed_only:
            q += " AND bs.is_confirmed = 0"
        if not show_canceled:
            q += " AND COALESCE(bs.canceled, 0) = 0"
        q += " ORDER BY bs.date DESC"
        rows = db.execute(q, params).fetchall()
    return [_session_to_dict(r) for r in rows]


@router.post("/sessions", status_code=201)
def create_session(body: SessionCreate):
    """Manually create a billing session without a calendar event."""
    if not body.client_id and not body.company_id:
        raise HTTPException(status_code=422, detail="Either client_id or company_id is required")

    with get_write_db() as db:
        rate = body.rate
        company_id = body.company_id
        is_prepaid = False

        if body.client_id:
            cl = db.execute(
                "SELECT bc.*, bco.default_rate, bco.id as co_id "
                "FROM billing_clients bc JOIN billing_companies bco ON bco.id = bc.company_id "
                "WHERE bc.id = ?", (body.client_id,)
            ).fetchone()
            if not cl:
                raise HTTPException(status_code=404, detail="Client not found")
            if rate is None:
                rate = cl["rate_override"] if cl["rate_override"] is not None else cl["default_rate"]
            company_id = cl["co_id"]
            is_prepaid = bool(cl["prepaid"])
        else:
            co = db.execute(
                "SELECT * FROM billing_companies WHERE id = ?", (body.company_id,)
            ).fetchone()
            if not co:
                raise HTTPException(status_code=404, detail="Company not found")
            if rate is None:
                rate = co["default_rate"]

        amount = 0.0 if is_prepaid else round(body.duration_hours * (rate or 0), 2)
        color_id = "3" if body.is_confirmed else "5"

        cur = db.execute(
            """INSERT INTO billing_sessions
               (date, client_id, company_id, duration_hours, rate, amount,
                is_confirmed, color_id, notes, dismissed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (body.date, body.client_id, company_id, body.duration_hours,
             rate, amount, int(body.is_confirmed), color_id, body.notes or ""),
        )
        db.commit()
        row = db.execute(
            "SELECT bs.*, bc.name as client_name, bc.prepaid, bco.name as company_name, bco.abbrev as company_abbrev "
            "FROM billing_sessions bs "
            "LEFT JOIN billing_clients bc ON bc.id = bs.client_id "
            "LEFT JOIN billing_companies bco ON bco.id = bs.company_id "
            "WHERE bs.id = ?", (cur.lastrowid,)
        ).fetchone()
    return _session_to_dict(row)


@router.post("/sessions/refresh-from-calendar")
def refresh_sessions_from_calendar():
    """Promote banana→grape sessions whose calendar event color has since changed to grape.
    Returns the number of sessions promoted.
    """
    with get_write_db() as db:
        promoted = _promote_banana_sessions(db)
    return {"promoted": promoted}


@router.post("/sessions/sync-session-numbers")
def sync_session_numbers():
    """Backfill session_number from the 'meeting' frontmatter field in Obsidian notes.

    For every confirmed session that has an obsidian_note_path but no session_number,
    reads the note frontmatter and writes the 'meeting' value to session_number.
    Safe to run repeatedly.
    """
    try:
        from connectors.obsidian import get_vault_path, _parse_frontmatter
    except ImportError:
        return {"error": "obsidian connector not available"}

    vault = get_vault_path()
    if not vault:
        return {"error": "vault not configured"}

    with get_write_db() as db:
        rows = db.execute(
            """
            SELECT bs.id, bs.obsidian_note_path, bc.obsidian_name, bs.date
            FROM billing_sessions bs
            LEFT JOIN billing_clients bc ON bc.id = bs.client_id
            WHERE bs.is_confirmed = 1
              AND bs.session_number IS NULL
              AND bs.obsidian_note_path IS NOT NULL
            """
        ).fetchall()

        updated = 0
        skipped = 0
        for row in rows:
            note_path = vault / row["obsidian_note_path"]
            if not note_path.exists():
                skipped += 1
                continue
            try:
                content = note_path.read_text(encoding="utf-8", errors="replace")
                meta, _ = _parse_frontmatter(content)
                raw_sn = meta.get("meeting")
                if raw_sn is None:
                    skipped += 1
                    continue
                sn = int(str(raw_sn).strip())
                db.execute("UPDATE billing_sessions SET session_number = ? WHERE id = ?", (sn, row["id"]))
                updated += 1
            except Exception as e:
                logger.warning("sync_session_numbers: error reading %s: %s", row["obsidian_note_path"], e)
                skipped += 1

        if updated:
            db.commit()

    return {"updated": updated, "skipped": skipped}


@router.post("/sessions/sync-calendar")
def sync_calendar_and_refresh():
    """Synchronously pull latest events from Google Calendar, then promote banana→grape sessions.

    Runs in the request thread so the caller can wait for completion before
    re-fetching the unprocessed queue.  Returns counts of synced events and
    promoted sessions.
    """
    synced = 0
    promoted = 0
    try:
        from connectors.calendar_sync import sync_calendar_events
        synced = sync_calendar_events()
    except ImportError:
        raise HTTPException(status_code=503, detail="Calendar connector not available")
    except Exception as e:
        logger.exception("Calendar sync failed")
        raise HTTPException(status_code=500, detail=str(e))

    with get_write_db() as db:
        promoted = _promote_banana_sessions(db)

    return {"synced": synced, "promoted": promoted}


@router.post("/sessions/relink")
def relink_sessions():
    """Re-link billing_sessions.client_id after a seed re-import.

    Matches obsidian_note_path to billing_clients.obsidian_name to restore
    client FK references that became stale when clients were re-inserted with
    new autoincrement IDs.
    """
    with get_write_db() as db:
        relinked = _relink_sessions_after_import(db)
    return {"relinked": relinked}


@router.get("/sessions/next-number")
def get_next_session_number(client_id: int):
    """Return the next session number for a client: MAX(COALESCE(session_number, row_number)) + 1."""
    with get_db_connection(readonly=True) as db:
        row = db.execute(
            """
            WITH sno AS (
                SELECT id,
                       ROW_NUMBER() OVER (ORDER BY date, id) AS rn
                FROM billing_sessions
                WHERE client_id = ? AND dismissed = 0
            )
            SELECT MAX(COALESCE(bs.session_number, sno.rn)) AS max_sno
            FROM billing_sessions bs
            JOIN sno ON sno.id = bs.id
            WHERE bs.client_id = ? AND bs.dismissed = 0
            """,
            (client_id, client_id)
        ).fetchone()
    return {"client_id": client_id, "next_number": (row["max_sno"] or 0) + 1}


@router.get("/sessions/{session_id}")
def get_session(session_id: int):
    with get_db_connection(readonly=True) as db:
        row = db.execute(
            "SELECT bs.*, bc.name AS client_name, bc.prepaid AS prepaid, "
            "bco.name AS company_name, bco.abbrev AS company_abbrev, bil.invoice_id AS invoice_id "
            "FROM billing_sessions bs "
            "LEFT JOIN billing_clients bc ON bc.id = bs.client_id "
            "LEFT JOIN billing_companies bco ON bco.id = bs.company_id "
            "LEFT JOIN billing_invoice_lines bil ON bil.id = bs.invoice_line_id "
            "WHERE bs.id = ?", (session_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_to_dict(row)


@router.patch("/sessions/{session_id}")
def update_session(session_id: int, body: SessionUpdate):
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items()}

    # When client_id is being set, auto-derive company_id from the client
    # unless the caller explicitly supplied a company_id too.
    if "client_id" in fields and fields["client_id"] is not None and "company_id" not in fields:
        with get_db_connection(readonly=True) as _db:
            cl_row = _db.execute(
                "SELECT company_id FROM billing_clients WHERE id = ?", (fields["client_id"],)
            ).fetchone()
        if cl_row:
            fields["company_id"] = cl_row["company_id"]

    clause, params = _build_update(fields, SESSION_ALLOWED)
    if not clause:
        raise HTTPException(status_code=400, detail="No valid fields")
    params.append(session_id)
    with get_write_db() as db:
        db.execute(f"UPDATE billing_sessions SET {clause} WHERE id = ?", params)
        db.commit()
        row = db.execute(
            "SELECT bs.*, bc.name AS client_name, bc.prepaid AS prepaid, "
            "bco.name AS company_name, bco.abbrev AS company_abbrev, bil.invoice_id AS invoice_id "
            "FROM billing_sessions bs "
            "LEFT JOIN billing_clients bc ON bc.id = bs.client_id "
            "LEFT JOIN billing_companies bco ON bco.id = bs.company_id "
            "LEFT JOIN billing_invoice_lines bil ON bil.id = bs.invoice_line_id "
            "WHERE bs.id = ?", (session_id,)
        ).fetchone()
    return _session_to_dict(row)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int):
    with get_write_db() as db:
        db.execute("DELETE FROM billing_sessions WHERE id = ?", (session_id,))
        db.commit()
    return {"ok": True}


@router.post("/sessions/{session_id}/unprocess")
def unprocess_session(session_id: int):
    """Move a confirmed session back to the unprocessed queue.

    For past sessions whose calendar event is currently grape (colorId='3'),
    also reverts the Google Calendar event color to banana (colorId='5') and
    updates local calendar_events accordingly — symmetric with confirm-past-banana.
    Returns {"need_reauth": true} if GCal write scope is missing.
    """
    with get_write_db() as db:
        row = db.execute(
            "SELECT bs.id, bs.invoice_line_id, bs.calendar_event_id, "
            "       bs.date, ce.color_id AS ce_color_id "
            "FROM billing_sessions bs "
            "LEFT JOIN calendar_events ce ON ce.id = bs.calendar_event_id "
            "WHERE bs.id = ?",
            (session_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")
        if not row["calendar_event_id"]:
            raise HTTPException(status_code=400, detail="Session has no calendar_event_id — cannot unprocess")

        today = __import__("datetime").date.today().isoformat()
        is_past_grape = (
            row["date"] is not None
            and row["date"] < today
            and row["ce_color_id"] == "3"
        )

        # For past grape events, revert GCal color to banana before touching the DB
        if is_past_grape:
            if not _has_calendar_write_scope():
                return {"need_reauth": True}
            try:
                from googleapiclient.discovery import build
                from connectors.google_auth import get_google_credentials

                creds = get_google_credentials()
                service = build("calendar", "v3", credentials=creds)
                service.events().patch(
                    calendarId="primary",
                    eventId=row["calendar_event_id"],
                    body={"colorId": "5"},
                ).execute()
                logger.info(
                    "unprocess_session: reverted GCal event %s colorId → banana",
                    row["calendar_event_id"],
                )
            except Exception as e:
                logger.error("unprocess_session: GCal revert failed: %s", e)
                raise HTTPException(status_code=500, detail=f"Failed to revert Google Calendar color: {e}")

            db.execute(
                "UPDATE calendar_events SET color_id='5' WHERE id=?",
                (row["calendar_event_id"],),
            )

        db.execute(
            "UPDATE billing_sessions SET is_confirmed=0, dismissed=0, color_id='5', invoice_line_id=NULL "
            "WHERE id=?",
            (session_id,),
        )
        db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Prepaid blocks
# ---------------------------------------------------------------------------

class PrepaidBlockCreate(BaseModel):
    client_id: int
    hours_purchased: float
    sessions_purchased: Optional[int] = None
    starting_after_date: Optional[str] = None  # YYYY-MM-DD
    hours_offset: Optional[float] = None  # pre-Dashy history offset


def _prepaid_block_to_dict(row, hours_used: float) -> dict:
    d = dict(row)
    d["hours_used"] = round(hours_used, 2)
    return d


@router.get("/prepaid-blocks")
def list_prepaid_blocks(client_id: Optional[int] = None):
    """Return prepaid blocks with computed hours_used."""
    with get_db_connection(readonly=True) as db:
        q = """
            SELECT pb.*, bc.name AS client_name,
                   COALESCE(SUM(bs.duration_hours), 0) AS hours_used
            FROM billing_prepaid_blocks pb
            JOIN billing_clients bc ON bc.id = pb.client_id
            LEFT JOIN billing_sessions bs
                   ON bs.client_id = pb.client_id
                   AND bs.dismissed = 0
                   AND (pb.starting_after_date IS NULL OR bs.date > pb.starting_after_date)
        """
        params: list = []
        if client_id:
            q += " WHERE pb.client_id = ?"
            params.append(client_id)
        q += " GROUP BY pb.id ORDER BY pb.created_at DESC"
        rows = db.execute(q, params).fetchall()
    return [dict(r) for r in rows]


@router.post("/prepaid-blocks", status_code=201)
def create_prepaid_block(body: PrepaidBlockCreate):
    """Create a prepaid block and automatically generate a draft invoice."""
    with get_write_db() as db:
        cl = db.execute(
            "SELECT bc.*, bco.default_rate, bco.id AS co_id, bco.name AS co_name, "
            "bco.abbrev AS co_abbrev, bco.invoice_prefix "
            "FROM billing_clients bc "
            "JOIN billing_companies bco ON bco.id = bc.company_id "
            "WHERE bc.id = ?", (body.client_id,)
        ).fetchone()
        if not cl:
            raise HTTPException(status_code=404, detail="Client not found")

        # Format starting_after_date for invoice description
        if body.starting_after_date:
            try:
                dt = datetime.strptime(body.starting_after_date, "%Y-%m-%d")
                date_label = f"{dt.strftime('%B')} {dt.day}, {dt.year}"
            except ValueError:
                date_label = body.starting_after_date
        else:
            date_label = "date TBD"

        n = body.hours_purchased
        n_str = str(int(n)) if n == int(n) else str(n)
        description = f"{n_str} hours of coaching beginning after {date_label}"

        rate = cl["rate_override"] if cl["rate_override"] is not None else cl["default_rate"]
        amount = round(body.hours_purchased * (rate or 0), 2)

        # Determine period_month from starting_after_date (or today)
        if body.starting_after_date:
            try:
                period_dt = datetime.strptime(body.starting_after_date, "%Y-%m-%d")
            except ValueError:
                period_dt = datetime.now()
        else:
            period_dt = datetime.now()
        period_month = period_dt.strftime("%Y-%m")
        year, month_num = period_dt.year, period_dt.month

        abbrev = (
            cl["co_abbrev"]
            or cl["invoice_prefix"]
            or cl["co_name"][:3].upper()
        )
        base_inv_num = _invoice_number_for_period(year, month_num, abbrev)

        # Find a unique invoice number (append -P, -P2, etc. to avoid collisions)
        candidate = f"{base_inv_num}-P"
        suffix = 2
        while db.execute(
            "SELECT 1 FROM billing_invoices WHERE invoice_number = ?", (candidate,)
        ).fetchone():
            candidate = f"{base_inv_num}-P{suffix}"
            suffix += 1
        invoice_number = candidate

        today = datetime.now().strftime("%Y-%m-%d")
        due_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

        cur = db.execute(
            """INSERT INTO billing_invoices
               (invoice_number, company_id, period_month, invoice_date,
                due_date, status, total_amount)
               VALUES (?, ?, ?, ?, ?, 'draft', ?)""",
            (invoice_number, cl["co_id"], period_month, today, due_date, amount),
        )
        invoice_id = cur.lastrowid

        db.execute(
            """INSERT INTO billing_invoice_lines
               (invoice_id, type, description, unit_cost, quantity, amount, sort_order)
               VALUES (?, 'prepaid', ?, ?, ?, ?, 1)""",
            (invoice_id, description, rate or 0, body.hours_purchased, amount),
        )

        cur2 = db.execute(
            """INSERT INTO billing_prepaid_blocks
               (client_id, sessions_purchased, hours_purchased, starting_after_date, invoice_id, hours_offset)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (body.client_id, body.sessions_purchased, body.hours_purchased,
             body.starting_after_date, invoice_id, body.hours_offset or 0),
        )
        block_id = cur2.lastrowid
        db.commit()

        row = db.execute(
            """SELECT pb.*, bc.name AS client_name, 0.0 AS hours_used
               FROM billing_prepaid_blocks pb
               JOIN billing_clients bc ON bc.id = pb.client_id
               WHERE pb.id = ?""", (block_id,)
        ).fetchone()

    return {**dict(row), "invoice_id": invoice_id, "invoice_number": invoice_number}


# ---------------------------------------------------------------------------
# Invoice prep — models
# ---------------------------------------------------------------------------

class PrepareInvoiceLine(BaseModel):
    type: str                          # sessions | expense | correction
    description: str
    date_range: Optional[str] = None
    unit_cost: Optional[float] = None
    quantity: Optional[float] = None
    amount: float
    sort_order: int = 0
    session_ids: list[int] = []        # billing_sessions to back-link


class PrepareCompanyRequest(BaseModel):
    company_id: int
    lines: list[PrepareInvoiceLine]
    invoice_number: Optional[str] = None   # override auto-generated value


class PrepareGenerateRequest(BaseModel):
    invoice_date: str   # YYYY-MM-DD
    services_date: str  # YYYY-MM-DD
    companies: list[PrepareCompanyRequest]


# ---------------------------------------------------------------------------
# Invoice prep — helpers
# ---------------------------------------------------------------------------

def _invoice_number_for_period(year: int, month: int, abbrev: str) -> str:
    """Return the canonical invoice number for a company + billing period.

    Format: YYYY-{ABBREV}-{MM}  e.g. 2026-ARB-03
    """
    return f"{year}-{abbrev}-{month:02d}"


def _prep_session_to_dict(row) -> dict:
    """Minimal session dict for prep view (already has client/company names joined)."""
    d = _session_to_dict(row)
    return d


# ---------------------------------------------------------------------------
# Invoice prep — GET /prepare/{year}/{month}
# ---------------------------------------------------------------------------

@router.get("/prepare/{year}/{month}")
def get_prepare_data(year: int, month: int):
    """Return session + company data needed to build the invoice prep UI."""
    period = f"{year}-{month:02d}"

    with get_db_connection(readonly=True) as db:
        companies_rows = db.execute(
            "SELECT * FROM billing_companies WHERE billing_method IS NOT NULL ORDER BY name"
        ).fetchall()

        result_companies = []
        for co in companies_rows:
            sessions_rows = db.execute(
                """
                SELECT bs.*, bc.name AS client_name, bc.prepaid,
                       bco.name AS company_name, bco.abbrev AS company_abbrev
                FROM billing_sessions bs
                LEFT JOIN billing_clients bc  ON bc.id  = bs.client_id
                LEFT JOIN billing_companies bco ON bco.id = bs.company_id
                WHERE bs.company_id = ? AND bs.date LIKE ?
                  AND bs.dismissed = 0
                ORDER BY bs.date
                """,
                (co["id"], f"{period}%"),
            ).fetchall()

            if not sessions_rows:
                continue  # skip companies with no activity this period

            confirmed = [_prep_session_to_dict(s) for s in sessions_rows if s["is_confirmed"]]
            projected = [_prep_session_to_dict(s) for s in sessions_rows if not s["is_confirmed"]]

            existing_inv = db.execute(
                "SELECT id, invoice_number, status FROM billing_invoices "
                "WHERE company_id = ? AND period_month = ?",
                (co["id"], period),
            ).fetchone()

            result_companies.append({
                "id": co["id"],
                "name": co["name"],
                "abbrev": co["abbrev"],
                "billing_method": co["billing_method"],
                "default_rate": co["default_rate"],
                "confirmed_sessions": confirmed,
                "projected_sessions": projected,
                "confirmed_total_hours": sum(s["duration_hours"] for s in sessions_rows if s["is_confirmed"]),
                "confirmed_total_amount": sum(s["amount"] for s in sessions_rows if s["is_confirmed"]),
                "projected_total_hours": sum(s["duration_hours"] for s in sessions_rows if not s["is_confirmed"]),
                "projected_total_amount": sum(s["amount"] for s in sessions_rows if not s["is_confirmed"]),
                "existing_invoice": dict(existing_inv) if existing_inv else None,
            })

    return {
        "year": year,
        "month": month,
        "period_month": period,
        "companies": result_companies,
    }


# ---------------------------------------------------------------------------
# Invoice prep — POST /prepare/{year}/{month}/generate
# ---------------------------------------------------------------------------

@router.post("/prepare/{year}/{month}/generate", status_code=201)
def generate_invoices(year: int, month: int, body: PrepareGenerateRequest):
    """Create draft billing_invoices + billing_invoice_lines for the given period."""
    period = f"{year}-{month:02d}"
    created = []

    with get_write_db() as db:
        for co_req in body.companies:
            if not co_req.lines:
                continue

            company = db.execute(
                "SELECT * FROM billing_companies WHERE id = ?", (co_req.company_id,)
            ).fetchone()
            if not company or not company["billing_method"]:
                continue

            # Skip companies with zero billable amount
            total_amount = round(sum(line.amount for line in co_req.lines), 2)
            if total_amount == 0:
                continue

            # Skip companies that already have an invoice for this period
            if db.execute(
                "SELECT 1 FROM billing_invoices WHERE company_id = ? AND period_month = ?",
                (co_req.company_id, period),
            ).fetchone():
                continue

            # Resolve invoice number — use override if provided, else derive from period
            if co_req.invoice_number and co_req.invoice_number.strip():
                invoice_number = co_req.invoice_number.strip()
            else:
                abbrev = (
                    company["abbrev"]
                    or company["invoice_prefix"]
                    or company["name"][:3].upper()
                )
                invoice_number = _invoice_number_for_period(year, month, abbrev)

            # Dates
            try:
                inv_date = datetime.strptime(body.invoice_date, "%Y-%m-%d")
            except ValueError:
                inv_date = datetime.now()
            due_date = (inv_date + timedelta(days=30)).strftime("%Y-%m-%d")

            # Insert invoice
            cur = db.execute(
                """
                INSERT INTO billing_invoices
                    (invoice_number, company_id, period_month, invoice_date,
                     services_date, due_date, status, total_amount)
                VALUES (?, ?, ?, ?, ?, ?, 'draft', ?)
                """,
                (
                    invoice_number, co_req.company_id, period,
                    body.invoice_date, body.services_date, due_date, total_amount,
                ),
            )
            invoice_id = cur.lastrowid

            # Insert lines + back-link sessions
            for line in sorted(co_req.lines, key=lambda x: x.sort_order):
                cur2 = db.execute(
                    """
                    INSERT INTO billing_invoice_lines
                        (invoice_id, type, description, date_range,
                         unit_cost, quantity, amount, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invoice_id, line.type, line.description, line.date_range,
                        line.unit_cost, line.quantity, round(line.amount, 2), line.sort_order,
                    ),
                )
                line_id = cur2.lastrowid

                if line.type == "sessions" and line.session_ids:
                    for sid in line.session_ids:
                        db.execute(
                            "UPDATE billing_sessions SET invoice_line_id = ? WHERE id = ?",
                            (line_id, sid),
                        )

        db.commit()

        # Re-fetch created invoices for response
        for co_req in body.companies:
            if not co_req.lines:
                continue
            row = db.execute(
                "SELECT bi.*, bco.name AS company_name "
                "FROM billing_invoices bi "
                "JOIN billing_companies bco ON bco.id = bi.company_id "
                "WHERE bi.company_id = ? AND bi.period_month = ? "
                "ORDER BY bi.id DESC LIMIT 1",
                (co_req.company_id, period),
            ).fetchone()
            if row:
                created.append({
                    "company_id": co_req.company_id,
                    "company_name": row["company_name"],
                    "invoice_number": row["invoice_number"],
                    "total_amount": row["total_amount"],
                    "status": row["status"],
                })

    return {"ok": True, "invoices": created}


# ---------------------------------------------------------------------------
# Invoice list / detail / update
# ---------------------------------------------------------------------------

class InvoiceLineInput(BaseModel):
    description: str
    amount: float
    date_range: Optional[str] = None


class InvoiceCreate(BaseModel):
    company_id: int
    invoice_number: str
    period_month: str            # YYYY-MM
    invoice_date: Optional[str] = None
    services_date: Optional[str] = None
    due_date: Optional[str] = None
    status: str = "sent"
    total_amount: float
    notes: Optional[str] = None
    lines: Optional[list[InvoiceLineInput]] = None


class InvoiceUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    services_date: Optional[str] = None


INVOICE_ALLOWED = {"status", "notes", "invoice_date", "due_date", "services_date", "sent_at"}


@router.post("/invoices", status_code=201)
def create_invoice(body: InvoiceCreate):
    """Manually create a historical invoice with optional line items."""
    sent_at = None
    if body.status == "sent":
        from datetime import datetime
        sent_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_write_db() as db:
        # Check for duplicate invoice number
        existing = db.execute(
            "SELECT id FROM billing_invoices WHERE invoice_number = ?",
            (body.invoice_number,),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Invoice number '{body.invoice_number}' already exists")

        cur = db.execute(
            """INSERT INTO billing_invoices
               (company_id, invoice_number, period_month, invoice_date, services_date,
                due_date, status, total_amount, notes, sent_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.company_id, body.invoice_number, body.period_month,
             body.invoice_date, body.services_date, body.due_date,
             body.status, body.total_amount, body.notes, sent_at),
        )
        invoice_id = cur.lastrowid

        if body.lines:
            for i, line in enumerate(body.lines):
                db.execute(
                    """INSERT INTO billing_invoice_lines
                       (invoice_id, type, description, amount, date_range, sort_order)
                       VALUES (?, 'manual', ?, ?, ?, ?)""",
                    (invoice_id, line.description, line.amount, line.date_range, i),
                )

        db.commit()

        inv = db.execute(
            "SELECT bi.*, bco.name AS company_name, 0 AS session_count "
            "FROM billing_invoices bi "
            "LEFT JOIN billing_companies bco ON bco.id = bi.company_id "
            "WHERE bi.id = ?",
            (invoice_id,),
        ).fetchone()

    return dict(inv)


@router.get("/invoices")
def list_invoices(
    company_id: Optional[int] = None,
    status: Optional[str] = None,
    period_month: Optional[str] = None,   # YYYY-MM  (exact month)
    period_year: Optional[int] = None,    # YYYY     (whole year, ignored if period_month set)
):
    """List all invoices with company name, status, and linked session count."""
    with get_db_connection(readonly=True) as db:
        q = """
            SELECT bi.*, bco.name AS company_name,
                   COUNT(DISTINCT bs.id) AS session_count,
                   (
                       SELECT COUNT(*)
                       FROM billing_sessions us
                       WHERE us.company_id = bi.company_id
                         AND substr(us.date, 1, 7) = bi.period_month
                         AND us.is_confirmed = 1
                         AND us.dismissed = 0
                         AND us.invoice_line_id IS NULL
                   ) AS unlinked_session_count
            FROM billing_invoices bi
            LEFT JOIN billing_companies bco ON bco.id = bi.company_id
            LEFT JOIN billing_invoice_lines bil ON bil.invoice_id = bi.id
            LEFT JOIN billing_sessions bs ON bs.invoice_line_id = bil.id
            WHERE 1=1
        """
        params: list = []
        if company_id:
            q += " AND bi.company_id = ?"
            params.append(company_id)
        if status:
            q += " AND bi.status = ?"
            params.append(status)
        if period_month:
            q += " AND bi.period_month = ?"
            params.append(period_month)
        elif period_year:
            q += " AND bi.period_month LIKE ?"
            params.append(f"{period_year}-%")
        q += " GROUP BY bi.id ORDER BY bi.invoice_date DESC, bi.id DESC"
        rows = db.execute(q, params).fetchall()
    return [dict(r) for r in rows]


@router.get("/invoices/csv-template")
def get_invoice_csv_template():
    """Return a downloadable CSV template for bulk invoice import."""
    from fastapi.responses import Response
    header = "company_name,invoice_number,period_month,invoice_date,total_amount,status,notes"
    example = "Acme Corp,2025-ACME-03,2025-03,2025-03-31,5000.00,sent,March advisory services"
    content = f"{header}\n{example}\n"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="invoice_import_template.csv"'},
    )


class InvoiceBulkImportRow(BaseModel):
    company_name: str
    invoice_number: str
    period_month: str
    invoice_date: Optional[str] = None
    total_amount: float
    status: str = "sent"
    notes: Optional[str] = None


class InvoiceBulkImportBody(BaseModel):
    rows: list[InvoiceBulkImportRow]


@router.post("/invoices/bulk-import")
def bulk_import_invoices(body: InvoiceBulkImportBody):
    """Bulk-create historical invoices from parsed CSV rows.

    Returns per-row results. Duplicate invoice numbers are skipped with an error.
    Unknown company names are also rejected per row.
    """
    from datetime import datetime as _dt

    with get_db_connection(readonly=True) as db:
        companies = {
            row["name"].lower(): row["id"]
            for row in db.execute("SELECT id, name FROM billing_companies").fetchall()
        }
        existing_numbers = {
            row[0]
            for row in db.execute("SELECT invoice_number FROM billing_invoices").fetchall()
        }

    results = []
    created = 0
    skipped = 0

    with get_write_db() as db:
        for i, row in enumerate(body.rows):
            row_num = i + 1

            # Resolve company
            company_id = companies.get(row.company_name.strip().lower())
            if not company_id:
                results.append({"row": row_num, "invoice_number": row.invoice_number,
                                 "status": "error", "error": f"Unknown company: '{row.company_name}'"})
                skipped += 1
                continue

            # Check for duplicate
            if row.invoice_number in existing_numbers:
                results.append({"row": row_num, "invoice_number": row.invoice_number,
                                 "status": "error", "error": "Duplicate invoice number"})
                skipped += 1
                continue

            sent_at = None
            if row.status == "sent":
                sent_at = row.invoice_date or _dt.utcnow().strftime("%Y-%m-%d")

            try:
                cur = db.execute(
                    """INSERT INTO billing_invoices
                       (company_id, invoice_number, period_month, invoice_date,
                        status, total_amount, notes, sent_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (company_id, row.invoice_number, row.period_month, row.invoice_date,
                     row.status, row.total_amount, row.notes, sent_at),
                )
                existing_numbers.add(row.invoice_number)
                results.append({"row": row_num, "invoice_number": row.invoice_number,
                                 "status": "created", "id": cur.lastrowid, "error": None})
                created += 1
            except Exception as e:
                results.append({"row": row_num, "invoice_number": row.invoice_number,
                                 "status": "error", "error": str(e)})
                skipped += 1

        db.commit()

    return {"created": created, "skipped": skipped, "results": results}


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int):
    """Return invoice detail with line items and linked sessions."""
    with get_db_connection(readonly=True) as db:
        inv = db.execute(
            "SELECT bi.*, bco.name AS company_name "
            "FROM billing_invoices bi "
            "LEFT JOIN billing_companies bco ON bco.id = bi.company_id "
            "WHERE bi.id = ?",
            (invoice_id,),
        ).fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")

        lines = db.execute(
            "SELECT * FROM billing_invoice_lines "
            "WHERE invoice_id = ? ORDER BY sort_order, id",
            (invoice_id,),
        ).fetchall()

        sessions = db.execute(
            """
            SELECT bs.*, bc.name AS client_name, bc.prepaid AS prepaid,
                   bco2.name AS company_name, bco2.abbrev AS company_abbrev, bil.invoice_id AS invoice_id
            FROM billing_sessions bs
            JOIN billing_invoice_lines bil ON bil.id = bs.invoice_line_id
            LEFT JOIN billing_clients bc ON bc.id = bs.client_id
            LEFT JOIN billing_companies bco2 ON bco2.id = bs.company_id
            WHERE bil.invoice_id = ?
            ORDER BY bs.date
            """,
            (invoice_id,),
        ).fetchall()

    result = dict(inv)
    result["lines"] = [dict(line) for line in lines]
    result["sessions"] = [_session_to_dict(s) for s in sessions]
    return result


@router.get("/invoices/{invoice_id}/unlinked-sessions")
def get_invoice_unlinked_sessions(invoice_id: int):
    """Return confirmed sessions for the invoice's company/period that have no invoice_line_id."""
    with get_db_connection(readonly=True) as db:
        inv = db.execute(
            "SELECT company_id, period_month FROM billing_invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")

        company_id = inv["company_id"]
        period_month = inv["period_month"]
        if not company_id or not period_month:
            return []

        rows = db.execute(
            """
            SELECT bs.*, bc.name AS client_name, bc.prepaid AS prepaid,
                   bco.name AS company_name, bco.abbrev AS company_abbrev,
                   NULL AS invoice_id
            FROM billing_sessions bs
            LEFT JOIN billing_clients bc ON bc.id = bs.client_id
            LEFT JOIN billing_companies bco ON bco.id = bs.company_id
            WHERE bs.company_id = ?
              AND substr(bs.date, 1, 7) = ?
              AND bs.is_confirmed = 1
              AND bs.dismissed = 0
              AND bs.invoice_line_id IS NULL
            ORDER BY bs.date
            """,
            (company_id, period_month),
        ).fetchall()

    return [_session_to_dict(r) for r in rows]


class ReconcileBody(BaseModel):
    session_ids: list[int]
    line_id: Optional[int] = None  # if omitted, a new sessions line is auto-created


@router.post("/invoices/{invoice_id}/reconcile")
def reconcile_invoice_sessions(invoice_id: int, body: ReconcileBody):
    """Link confirmed sessions to an invoice line on this invoice.

    If line_id is omitted (e.g. CSV-imported invoice with no lines), a new
    'sessions' line is auto-created from the selected sessions' totals.
    """
    if not body.session_ids:
        raise HTTPException(status_code=400, detail="No sessions provided")

    with get_write_db() as db:
        inv = db.execute(
            "SELECT id FROM billing_invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")

        if body.line_id is not None:
            # Verify the line belongs to this invoice
            line = db.execute(
                "SELECT id FROM billing_invoice_lines WHERE id = ? AND invoice_id = ?",
                (body.line_id, invoice_id),
            ).fetchone()
            if not line:
                raise HTTPException(status_code=404, detail="Line not found on this invoice")
            line_id = body.line_id
        else:
            # Auto-create a sessions line summing the selected sessions
            placeholders = ",".join("?" * len(body.session_ids))
            agg = db.execute(
                f"SELECT SUM(duration_hours) AS hrs, SUM(amount) AS total "
                f"FROM billing_sessions WHERE id IN ({placeholders})",
                body.session_ids,
            ).fetchone()
            total_hrs = round(agg["hrs"] or 0, 2)
            total_amt = round(agg["total"] or 0, 2)
            cur = db.execute(
                """INSERT INTO billing_invoice_lines
                   (invoice_id, type, description, quantity, amount, sort_order)
                   VALUES (?, 'sessions', 'Sessions', ?, ?, 1)""",
                (invoice_id, total_hrs, total_amt),
            )
            line_id = cur.lastrowid

        placeholders = ",".join("?" * len(body.session_ids))
        db.execute(
            f"UPDATE billing_sessions SET invoice_line_id = ? WHERE id IN ({placeholders})",
            [line_id, *body.session_ids],
        )
        db.commit()

    return {"ok": True, "linked": len(body.session_ids), "line_id": line_id}


class AddInvoiceLineBody(BaseModel):
    description: str
    date_range: Optional[str] = None
    unit_cost: Optional[float] = None
    quantity: Optional[float] = None
    amount: float


@router.post("/invoices/{invoice_id}/lines", status_code=201)
def add_invoice_line(invoice_id: int, body: AddInvoiceLineBody):
    """Add a manual line item to an existing invoice and recompute total_amount."""
    with get_write_db() as db:
        inv = db.execute(
            "SELECT id FROM billing_invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")

        # Determine sort_order after existing lines
        max_sort = db.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM billing_invoice_lines WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()[0]

        db.execute(
            """INSERT INTO billing_invoice_lines
               (invoice_id, type, description, date_range, unit_cost, quantity, amount, sort_order)
               VALUES (?, 'manual', ?, ?, ?, ?, ?, ?)""",
            (invoice_id, body.description, body.date_range,
             body.unit_cost, body.quantity, body.amount, max_sort + 1),
        )

        # Recompute total_amount as sum of all lines
        new_total = db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM billing_invoice_lines WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()[0]
        db.execute(
            "UPDATE billing_invoices SET total_amount = ? WHERE id = ?",
            (round(new_total, 2), invoice_id),
        )
        db.commit()

    # Return the full updated invoice detail
    return get_invoice(invoice_id)


@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: int):
    """Delete an invoice, unlink its sessions, and remove the PDF file if present."""
    with get_write_db() as db:
        inv = db.execute(
            "SELECT id, pdf_path FROM billing_invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")
        # Unlink sessions that point to this invoice's lines
        db.execute(
            "UPDATE billing_sessions SET invoice_line_id = NULL "
            "WHERE invoice_line_id IN (SELECT id FROM billing_invoice_lines WHERE invoice_id = ?)",
            (invoice_id,),
        )
        db.execute("DELETE FROM billing_invoice_payments WHERE invoice_id = ?", (invoice_id,))
        db.execute("DELETE FROM billing_invoice_lines WHERE invoice_id = ?", (invoice_id,))
        db.execute("DELETE FROM billing_invoices WHERE id = ?", (invoice_id,))
        db.commit()
    # Remove PDF file from disk if it exists
    if inv["pdf_path"]:
        try:
            Path(inv["pdf_path"]).unlink(missing_ok=True)
        except Exception:
            pass
    return {"ok": True}


@router.patch("/invoices/{invoice_id}")
def update_invoice(invoice_id: int, body: InvoiceUpdate):
    """Update invoice status, notes, or dates."""
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items()
              if k in INVOICE_ALLOWED and v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No valid fields")
    clause, params = _build_update(fields, INVOICE_ALLOWED)
    params.append(invoice_id)
    with get_write_db() as db:
        db.execute(f"UPDATE billing_invoices SET {clause} WHERE id = ?", params)
        db.commit()
        inv = db.execute(
            "SELECT bi.*, bco.name AS company_name, "
            "COUNT(DISTINCT bs.id) AS session_count "
            "FROM billing_invoices bi "
            "LEFT JOIN billing_companies bco ON bco.id = bi.company_id "
            "LEFT JOIN billing_invoice_lines bil ON bil.invoice_id = bi.id "
            "LEFT JOIN billing_sessions bs ON bs.invoice_line_id = bil.id "
            "WHERE bi.id = ? GROUP BY bi.id",
            (invoice_id,),
        ).fetchone()
    return dict(inv)


# ---------------------------------------------------------------------------
# Billing & payment summary
# ---------------------------------------------------------------------------

@router.get("/summary")
def get_billing_summary(year: Optional[int] = None):
    """Return billing grid (invoiced/confirmed/projected by company × month)
    and cash-received totals for a given year.
    """
    if year is None:
        year = datetime.now(timezone.utc).year

    months = [f"{year}-{m:02d}" for m in range(1, 13)]
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")

    with get_db_connection(readonly=True) as db:
        companies = db.execute(
            "SELECT id, name, abbrev FROM billing_companies WHERE active=1 ORDER BY name"
        ).fetchall()

        # Invoice totals by company × period_month
        inv_rows = db.execute(
            """SELECT company_id, period_month,
                      SUM(total_amount) AS total,
                      GROUP_CONCAT(DISTINCT status) AS statuses
               FROM billing_invoices
               WHERE period_month LIKE ?
               GROUP BY company_id, period_month""",
            (f"{year}-%",),
        ).fetchall()

        # Session amounts by company × month (uses stored amount; prepaid sessions have amount=0)
        sess_rows = db.execute(
            """SELECT company_id,
                      substr(date, 1, 7) AS month,
                      SUM(CASE WHEN is_confirmed=1 THEN amount ELSE 0 END) AS confirmed,
                      SUM(CASE WHEN is_confirmed=0 THEN amount ELSE 0 END) AS projected,
                      SUM(CASE WHEN is_confirmed=1 THEN duration_hours ELSE 0 END) AS confirmed_hrs,
                      SUM(CASE WHEN is_confirmed=0 THEN duration_hours ELSE 0 END) AS projected_hrs
               FROM billing_sessions
               WHERE date LIKE ? AND dismissed=0 AND company_id IS NOT NULL
               GROUP BY company_id, month""",
            (f"{year}-%",),
        ).fetchall()

        # Cash received by month — invoice-linked payments + unlinked payments with a company_id
        pay_rows = db.execute(
            """SELECT month, SUM(total) AS total FROM (
                   SELECT substr(p.date, 1, 7) AS month, ip.amount_applied AS total
                   FROM billing_invoice_payments ip
                   JOIN billing_payments p ON p.id = ip.payment_id
                   WHERE p.date LIKE ?
               UNION ALL
                   SELECT substr(date, 1, 7) AS month, ABS(amount) AS total
                   FROM billing_payments
                   WHERE company_id IS NOT NULL
                     AND id NOT IN (SELECT payment_id FROM billing_invoice_payments)
                     AND date LIKE ?
               ) GROUP BY month""",
            (f"{year}-%", f"{year}-%"),
        ).fetchall()

    inv_map: dict = {}
    for r in inv_rows:
        inv_map[(r["company_id"], r["period_month"])] = {
            "invoiced": r["total"] or 0.0,
            "statuses": r["statuses"] or "",
        }

    sess_map: dict = {}
    for r in sess_rows:
        sess_map[(r["company_id"], r["month"])] = {
            "confirmed":     r["confirmed"]     or 0.0,
            "projected":     r["projected"]     or 0.0,
            "confirmed_hrs": r["confirmed_hrs"] or 0.0,
            "projected_hrs": r["projected_hrs"] or 0.0,
        }

    pay_map = {r["month"]: r["total"] or 0.0 for r in pay_rows}

    company_data = []
    for co in companies:
        monthly = {}
        co_total = 0.0
        has_any = False

        for month in months:
            inv  = inv_map.get((co["id"], month))
            sess = sess_map.get((co["id"], month), {})

            if inv:
                cell = {
                    "invoiced":      inv["invoiced"],
                    "statuses":      inv["statuses"],
                    "confirmed":     None,
                    "projected":     None,
                    "confirmed_hrs": None,
                    "projected_hrs": None,
                }
                co_total += inv["invoiced"]
                has_any = True
            else:
                confirmed = sess.get("confirmed", 0.0)
                projected = sess.get("projected", 0.0)
                if confirmed or projected:
                    cell = {
                        "invoiced":      None,
                        "statuses":      None,
                        "confirmed":     confirmed,
                        "projected":     projected,
                        "confirmed_hrs": sess.get("confirmed_hrs", 0.0),
                        "projected_hrs": sess.get("projected_hrs", 0.0),
                    }
                    co_total += confirmed + projected
                    has_any = True
                else:
                    cell = None

            monthly[month] = cell

        if has_any:
            company_data.append({
                "id":     co["id"],
                "name":   co["name"],
                "abbrev": co["abbrev"],
                "monthly": monthly,
                "total":   co_total,
            })

    payments_by_month = {m: pay_map.get(m, 0.0) for m in months}

    return {
        "year":             year,
        "months":           months,
        "current_month":    current_month,
        "companies":        company_data,
        "payments_by_month": payments_by_month,
        "payments_total":   sum(payments_by_month.values()),
    }


# ---------------------------------------------------------------------------
# Payments (LunchMoney)
# ---------------------------------------------------------------------------

class SingleAssignment(BaseModel):
    invoice_id: int
    amount_applied: float


class PaymentUpdate(BaseModel):
    company_id: Optional[int] = None


@router.post("/lunchmoney/sync")
def sync_lunchmoney(days_back: int = 180, clear: bool = False):
    """Trigger a LunchMoney transaction sync into billing_payments.

    If clear=true, wipes billing_invoice_payments and billing_payments first,
    then re-imports from scratch.
    """
    if clear:
        with get_write_db() as db:
            db.execute("DELETE FROM billing_invoice_payments")
            db.execute("DELETE FROM billing_payments")
            db.commit()
    try:
        from connectors.lunchmoney import sync_lunchmoney_transactions
        result = sync_lunchmoney_transactions(days_back=days_back)
        if clear:
            result["cleared"] = True
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/lunchmoney/relink-companies")
def relink_payment_companies():
    """Back-fill company_id on billing_payments with no company set.

    Matches payee + notes against company name and abbrev.
    Returns count of payments updated.
    """
    try:
        from connectors.lunchmoney import infer_company_ids_for_existing
        with get_write_db() as db:
            updated = infer_company_ids_for_existing(db)
        return {"updated": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/lunchmoney/check")
def check_lunchmoney_connection():
    try:
        from connectors.lunchmoney import check_lunchmoney
        return check_lunchmoney()
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/payments")
def list_payments(unmatched_only: bool = False):
    """List all billing payments with invoice assignments and fuzzy match suggestions."""
    from collections import defaultdict

    with get_db_connection(readonly=True) as db:
        payment_rows = db.execute(
            "SELECT * FROM billing_payments ORDER BY date DESC, id DESC"
        ).fetchall()

        assign_rows = db.execute(
            """SELECT bip.id, bip.payment_id, bip.invoice_id, bip.amount_applied,
                      bi.invoice_number, bco.name AS company_name
               FROM billing_invoice_payments bip
               JOIN billing_invoices bi  ON bi.id  = bip.invoice_id
               JOIN billing_companies bco ON bco.id = bi.company_id"""
        ).fetchall()

        open_invoices = db.execute(
            """SELECT bi.id, bi.invoice_number, bi.total_amount, bi.due_date,
                      bco.name AS company_name, bco.abbrev
               FROM billing_invoices bi
               JOIN billing_companies bco ON bco.id = bi.company_id
               WHERE bi.status NOT IN ('paid', 'cancelled')
               ORDER BY bi.due_date"""
        ).fetchall()

    assign_by_payment: dict = defaultdict(list)
    for a in assign_rows:
        assign_by_payment[a["payment_id"]].append({
            "id": a["id"],
            "invoice_id": a["invoice_id"],
            "invoice_number": a["invoice_number"],
            "company_name": a["company_name"],
            "amount_applied": a["amount_applied"],
        })

    result = []
    for p in payment_rows:
        assignments = assign_by_payment.get(p["id"], [])
        if unmatched_only and assignments:
            continue

        # Suggestions: exact amount match only (name matching was too broad — returned all
        # company invoices for any payment from that company, flooding the assignment panel)
        suggested: list[int] = []
        if not assignments:
            abs_amt = abs(float(p["amount"]))
            for inv in open_invoices:
                if abs(float(inv["total_amount"]) - abs_amt) < 0.01:
                    suggested.append(inv["id"])

        d = dict(p)
        d["assignments"] = assignments
        d["suggested_invoice_ids"] = suggested
        result.append(d)

    return result


@router.patch("/payments/{payment_id}")
def update_payment(payment_id: int, body: PaymentUpdate):
    """Update mutable fields on a payment (currently: company_id)."""
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    clause = ", ".join(f"{k} = ?" for k in fields)
    params = list(fields.values()) + [payment_id]
    with get_write_db() as db:
        if not db.execute("SELECT 1 FROM billing_payments WHERE id=?", (payment_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Payment not found")
        db.execute(f"UPDATE billing_payments SET {clause} WHERE id = ?", params)
        db.commit()
    return {"ok": True}


def _sync_invoice_payment_status(db, invoice_id: int) -> None:
    """Recalculate and persist paid/partial/sent status for an invoice based on applied payments."""
    inv = db.execute(
        "SELECT status, total_amount FROM billing_invoices WHERE id=?", (invoice_id,)
    ).fetchone()
    if not inv or inv["status"] == "draft":
        return
    total = float(inv["total_amount"] or 0)
    paid = float(
        db.execute(
            "SELECT COALESCE(SUM(amount_applied), 0) AS s FROM billing_invoice_payments WHERE invoice_id=?",
            (invoice_id,),
        ).fetchone()["s"]
    )
    from app_config import get_dashy_config
    _tol = get_dashy_config().get("invoice", {}).get("payment_tolerance_dollars", 1.00)
    if total > 0 and paid >= total - _tol:
        new_status = "paid"
    elif paid > 0.01:
        new_status = "partial"
    else:
        new_status = "sent"
    if new_status != inv["status"]:
        db.execute("UPDATE billing_invoices SET status=? WHERE id=?", (new_status, invoice_id))


@router.post("/payments/{payment_id}/assign")
def assign_payment(payment_id: int, body: SingleAssignment):
    """Add or update a single invoice assignment for a payment."""
    with get_write_db() as db:
        if not db.execute("SELECT 1 FROM billing_payments WHERE id=?", (payment_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Payment not found")
        existing = db.execute(
            "SELECT id FROM billing_invoice_payments WHERE invoice_id=? AND payment_id=?",
            (body.invoice_id, payment_id),
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE billing_invoice_payments SET amount_applied=? WHERE id=?",
                (body.amount_applied, existing["id"]),
            )
        else:
            db.execute(
                "INSERT INTO billing_invoice_payments (invoice_id, payment_id, amount_applied) "
                "VALUES (?, ?, ?)",
                (body.invoice_id, payment_id, body.amount_applied),
            )
        _sync_invoice_payment_status(db, body.invoice_id)
        db.commit()
    return {"ok": True}


@router.delete("/invoice-payments/{assignment_id}")
def remove_invoice_payment(assignment_id: int):
    """Remove a specific invoice–payment link."""
    with get_write_db() as db:
        row = db.execute(
            "SELECT invoice_id FROM billing_invoice_payments WHERE id=?", (assignment_id,)
        ).fetchone()
        db.execute("DELETE FROM billing_invoice_payments WHERE id=?", (assignment_id,))
        if row:
            _sync_invoice_payment_status(db, row["invoice_id"])
        db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# GET /api/billing/payables
# ---------------------------------------------------------------------------

def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """Return (year, month) shifted by delta months."""
    month += delta
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    return year, month


@router.get("/payables")
def get_payables(block: int = 0, company_id: int | None = None):
    """
    Return payables within a 6-month block for all eligible companies (or one).

    block=0: current month + 5 prior months (most recent block)
    block=1: prior 6 months, etc.
    company_id: if provided, restrict to that company only.

    Eligible = has sent/partial/paid invoices in block OR unbilled confirmed
    sessions in the current month.

    Returns:
      block_start, block_end  — "YYYY-MM" strings
      is_current_block        — True when block=0
      current_month           — "YYYY-MM" of today (only when is_current_block)
      companies               — array sorted alphabetically by company name, each with:
                                  company_id, company_name, unbilled_amount, invoices[]
    """
    from collections import defaultdict
    from datetime import date
    today = date.today()

    # Compute block bounds
    end_year, end_month = _add_months(today.year, today.month, -block * 6)
    start_year, start_month = _add_months(end_year, end_month, -5)

    block_start = f"{start_year}-{start_month:02d}"
    block_end   = f"{end_year}-{end_month:02d}"
    is_current  = (block == 0)
    cur_month   = f"{today.year}-{today.month:02d}" if is_current else None

    co_filter     = "AND bi.company_id = ?" if company_id else ""
    ub_co_filter  = "AND bs.company_id = ?" if company_id else ""
    co_param      = [company_id] if company_id else []

    with get_db_connection(readonly=True) as db:
        # All sent/partial/paid invoices in block (one query for all companies)
        inv_rows = db.execute(
            f"""
            SELECT
                bi.id,
                bi.company_id,
                bc.name          AS company_name,
                bi.invoice_number,
                bi.period_month,
                bi.invoice_date,
                bi.total_amount,
                bi.status,
                CASE
                  WHEN bi.status = 'paid' AND COALESCE(SUM(bip.amount_applied), 0) = 0
                  THEN COALESCE(bi.total_amount, 0)
                  ELSE COALESCE(SUM(bip.amount_applied), 0)
                END AS paid_amount
            FROM billing_invoices bi
            JOIN billing_companies bc ON bc.id = bi.company_id
            LEFT JOIN billing_invoice_payments bip ON bip.invoice_id = bi.id
            WHERE bi.status IN ('sent', 'partial', 'paid')
              AND bi.period_month BETWEEN ? AND ?
              {co_filter}
            GROUP BY bi.id
            ORDER BY bc.name, bi.period_month DESC, bi.id DESC
            """,
            [block_start, block_end] + co_param,
        ).fetchall()

        # Unbilled confirmed sessions per company for current month.
        # "Unbilled" = not yet sent: invoice_line_id IS NULL, or linked to a draft invoice.
        unbilled_by_co: dict[int, float] = {}
        if is_current and cur_month:
            ub_rows = db.execute(
                f"""
                SELECT bs.company_id,
                       bc.name AS company_name,
                       COALESCE(SUM(bs.amount), 0) AS total
                FROM billing_sessions bs
                JOIN billing_companies bc ON bc.id = bs.company_id
                LEFT JOIN billing_invoice_lines bil ON bil.id = bs.invoice_line_id
                LEFT JOIN billing_invoices bi ON bi.id = bil.invoice_id
                WHERE bs.is_confirmed = 1
                  AND bs.amount > 0
                  AND strftime('%Y-%m', bs.date) = ?
                  AND (bs.invoice_line_id IS NULL OR bi.status = 'draft')
                  {ub_co_filter}
                GROUP BY bs.company_id
                """,
                [cur_month] + co_param,
            ).fetchall()
            for r in ub_rows:
                unbilled_by_co[r["company_id"]] = r["total"]
            # Capture company names from unbilled rows too
            ub_names = {r["company_id"]: r["company_name"] for r in ub_rows}
        else:
            ub_names: dict[int, str] = {}

    # Group invoices by company
    inv_by_co: dict[int, list[dict]] = defaultdict(list)
    co_names: dict[int, str] = {}
    for r in inv_rows:
        co_names[r["company_id"]] = r["company_name"]
        inv_by_co[r["company_id"]].append({
            "id":             r["id"],
            "invoice_number": r["invoice_number"],
            "period_month":   r["period_month"],
            "invoice_date":   r["invoice_date"],
            "total_amount":   r["total_amount"],
            "paid_amount":    r["paid_amount"],
            "status":         r["status"],
        })
    co_names.update(ub_names)

    # Union of companies that have invoices or unbilled sessions
    all_co_ids = set(inv_by_co.keys()) | set(unbilled_by_co.keys())

    companies = sorted(
        [
            {
                "company_id":      cid,
                "company_name":    co_names.get(cid, ""),
                "unbilled_amount": unbilled_by_co.get(cid, 0.0) if is_current else None,
                "invoices":        inv_by_co.get(cid, []),
            }
            for cid in all_co_ids
        ],
        key=lambda x: x["company_name"],
    )

    return {
        "block_start":      block_start,
        "block_end":        block_end,
        "is_current_block": is_current,
        "current_month":    cur_month,
        "companies":        companies,
    }
