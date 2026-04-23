"""Read-only endpoints for dashy_install.json and dashy_config.json."""

import json

from fastapi import APIRouter, HTTPException

from app_config import get_dashy_config, get_install_config
from config import REPO_ROOT

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/install")
def read_install_config():
    """Return the user-visible portion of dashy_install.json (no secrets)."""
    ic = get_install_config()
    return {
        "user": ic.get("user", {}),
        "obsidian": {
            "vault_path": ic.get("obsidian", {}).get("vault_path", ""),
            "folders": ic.get("obsidian", {}).get("folders", {}),
        },
        "calendar": ic.get("calendar", {}),
    }


@router.get("/operational")
def read_operational_config():
    """Return dashy_config.json (all sections)."""
    return get_dashy_config()


@router.get("/sidebar")
def read_sidebar_config():
    """Return sidebar.config.json from the repo root."""
    config_path = REPO_ROOT / "sidebar.config.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="sidebar.config.json not found")
    return json.loads(config_path.read_text())
