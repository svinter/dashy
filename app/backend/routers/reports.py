"""Reports API — daily digest run history."""

import json

from fastapi import APIRouter

from database import get_db_connection

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/digests")
def get_digest_runs():
    """Return the last 5 digest runs, most recent first."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            """
            SELECT id, run_date, sent_at,
                   today_sessions, tomorrow_sessions,
                   note_creation, granola_sync,
                   unprocessed_sessions, backup_summary
            FROM digest_runs
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()

    def _parse(val):
        if val is None:
            return None
        try:
            return json.loads(val)
        except Exception:
            return val

    return [
        {
            "id": r["id"],
            "run_date": r["run_date"],
            "sent_at": r["sent_at"],
            "today_sessions": _parse(r["today_sessions"]),
            "tomorrow_sessions": _parse(r["tomorrow_sessions"]),
            "note_creation": _parse(r["note_creation"]),
            "granola_sync": _parse(r["granola_sync"]),
            "unprocessed_sessions": _parse(r["unprocessed_sessions"]),
            "backup_summary": _parse(r["backup_summary"]),
        }
        for r in rows
    ]
