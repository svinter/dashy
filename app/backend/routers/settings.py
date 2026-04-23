"""Module visibility preferences — GET/PUT /api/settings/modules."""

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import REPO_ROOT
from database import get_db_connection

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _load_sidebar_config() -> dict:
    config_path = REPO_ROOT / "sidebar.config.json"
    if not config_path.exists():
        return {"sections": []}
    return json.loads(config_path.read_text())


@router.get("/modules")
def list_modules():
    """Return all sidebar modules with current visibility from dashy_module_prefs."""
    config = _load_sidebar_config()

    # Read all persisted prefs
    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT module_id, visible FROM dashy_module_prefs").fetchall()
    prefs = {row["module_id"]: bool(row["visible"]) for row in rows}

    result = []
    for section in config.get("sections", []):
        section_label = section.get("label") or section.get("id", "")
        for item in section.get("items", []):
            module_id = item["id"]
            result.append({
                "module_id": module_id,
                "label": item.get("label", module_id),
                "route": item.get("route", ""),
                "connector": item.get("connector"),
                "section_id": section.get("id"),
                "section_label": section_label,
                "visible": prefs.get(module_id, True),
            })
    return result


class ModuleVisibilityUpdate(BaseModel):
    visible: bool


@router.put("/modules/{module_id}")
def update_module_visibility(module_id: str, body: ModuleVisibilityUpdate):
    """Upsert visibility pref for a sidebar module."""
    config = _load_sidebar_config()
    known_ids = {
        item["id"]
        for section in config.get("sections", [])
        for item in section.get("items", [])
    }
    if module_id not in known_ids:
        raise HTTPException(status_code=404, detail=f"Unknown module '{module_id}'")

    visible_int = 1 if body.visible else 0
    now = datetime.utcnow().isoformat()
    with get_db_connection() as db:
        db.execute(
            """
            INSERT INTO dashy_module_prefs (module_id, visible, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(module_id) DO UPDATE SET visible = excluded.visible, updated_at = excluded.updated_at
            """,
            (module_id, visible_int, now),
        )
        db.commit()
    return {"module_id": module_id, "visible": body.visible}
