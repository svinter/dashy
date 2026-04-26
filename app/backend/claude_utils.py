"""
claude_utils.py — Claude API usage logging helpers.

Two variants:
  log_claude_usage(...)          — uses FastAPI's get_db() / get_write_db()
  log_claude_usage_standalone(…) — opens its own sqlite3 connection; safe to
                                   import from pipeline scripts outside FastAPI.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing helpers
# ---------------------------------------------------------------------------

def _get_pricing() -> tuple[float, float]:
    """Return (input_cost_per_million, output_cost_per_million) from dashy_config.json."""
    try:
        from app_config import get_dashy_config
        cfg = get_dashy_config().get("claude", {})
        inp = float(cfg.get("sonnet_input_cost_per_million", 3.00))
        out = float(cfg.get("sonnet_output_cost_per_million", 15.00))
        return inp, out
    except Exception:
        return 3.00, 15.00


def _compute_cost(input_tokens: int, output_tokens: int) -> float:
    inp_rate, out_rate = _get_pricing()
    return (input_tokens / 1_000_000) * inp_rate + (output_tokens / 1_000_000) * out_rate


# ---------------------------------------------------------------------------
# FastAPI variant — uses shared DB connection from database.py
# ---------------------------------------------------------------------------

def log_claude_usage(
    feature: str,
    input_tokens: int,
    output_tokens: int,
    model: str,
    notes: str | None = None,
) -> None:
    """Log one Claude API call. Call this from any FastAPI router after a Claude request."""
    cost = _compute_cost(input_tokens, output_tokens)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        from database import get_write_db
        with get_write_db() as db:
            db.execute(
                """
                INSERT INTO claude_usage_log
                    (timestamp, feature, input_tokens, output_tokens, cost_usd, model, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (timestamp, feature, input_tokens, output_tokens, cost, model, notes),
            )
            db.commit()
    except Exception as exc:
        logger.warning("Failed to log Claude usage: %s", exc)


# ---------------------------------------------------------------------------
# Standalone variant — no FastAPI dependency; safe for pipeline scripts
# ---------------------------------------------------------------------------

def _get_db_path() -> Path:
    import os
    return Path(os.environ.get("DASHBOARD_DATA_DIR", Path.home() / ".personal-dashboard")) / "dashboard.db"


def log_claude_usage_standalone(
    feature: str,
    input_tokens: int,
    output_tokens: int,
    model: str,
    notes: str | None = None,
) -> None:
    """Log one Claude API call from outside FastAPI (e.g. a pipeline script).

    Example::

        from claude_utils import log_claude_usage_standalone
        log_claude_usage_standalone(
            feature='book_enrichment',
            input_tokens=500,
            output_tokens=100,
            model='claude-sonnet-4-20250514',
        )
    """
    cost = _compute_cost(input_tokens, output_tokens)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    db_path = _get_db_path()
    try:
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute(
            """
            INSERT INTO claude_usage_log
                (timestamp, feature, input_tokens, output_tokens, cost_usd, model, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (timestamp, feature, input_tokens, output_tokens, cost, model, notes),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("Failed to log Claude usage (standalone): %s", exc)
