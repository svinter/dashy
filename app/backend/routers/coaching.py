import json
import re
from datetime import date
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db

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
            SELECT id, client_id, date, session_number,
                   ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY date) AS rn
            FROM billing_sessions
            WHERE is_confirmed = 1
        ),
        ranked AS (
            SELECT sno.client_id, sno.date,
                   COALESCE(sno.session_number, sno.rn) AS display_session_number,
                   ROW_NUMBER() OVER (PARTITION BY sno.client_id ORDER BY sno.date DESC) AS recency
            FROM sno
            WHERE sno.client_id IN ({placeholders})
        )
        SELECT client_id, date, display_session_number
        FROM ranked WHERE recency = 1
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
            f"""SELECT project_id, COUNT(*) as cnt
                FROM billing_sessions
                WHERE project_id IN ({ph}) AND is_confirmed = 1
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
