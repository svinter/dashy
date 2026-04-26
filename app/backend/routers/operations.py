"""
GET /api/operations/claude-usage — Claude API cost & token usage aggregates.
"""

from __future__ import annotations

from fastapi import APIRouter
from database import get_db

router = APIRouter(prefix="/api/operations", tags=["operations"])


@router.get("/claude-usage")
def get_claude_usage():
    db = get_db()

    # -----------------------------------------------------------------------
    # All-time totals
    # -----------------------------------------------------------------------
    row = db.execute(
        """
        SELECT
            COUNT(*)            AS call_count,
            COALESCE(SUM(input_tokens), 0)  AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cost_usd), 0.0)    AS cost_usd
        FROM claude_usage_log
        """
    ).fetchone()
    all_time = {
        "call_count":     row["call_count"],
        "input_tokens":   row["input_tokens"],
        "output_tokens":  row["output_tokens"],
        "cost_usd":       round(row["cost_usd"], 6),
    }

    # -----------------------------------------------------------------------
    # Daily — last 7 days
    # -----------------------------------------------------------------------
    daily_rows = db.execute(
        """
        SELECT
            DATE(timestamp) AS period,
            COUNT(*)             AS call_count,
            SUM(input_tokens)    AS input_tokens,
            SUM(output_tokens)   AS output_tokens,
            SUM(cost_usd)        AS cost_usd
        FROM claude_usage_log
        WHERE DATE(timestamp) >= DATE('now', '-6 days')
        GROUP BY DATE(timestamp)
        ORDER BY period DESC
        """
    ).fetchall()
    daily = [
        {
            "period":        r["period"],
            "call_count":    r["call_count"],
            "input_tokens":  r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "cost_usd":      round(r["cost_usd"], 6),
        }
        for r in daily_rows
    ]

    # -----------------------------------------------------------------------
    # Weekly — last 8 weeks (ISO week, Monday-based)
    # -----------------------------------------------------------------------
    weekly_rows = db.execute(
        """
        SELECT
            STRFTIME('%Y-W%W', timestamp) AS period,
            COUNT(*)             AS call_count,
            SUM(input_tokens)    AS input_tokens,
            SUM(output_tokens)   AS output_tokens,
            SUM(cost_usd)        AS cost_usd
        FROM claude_usage_log
        WHERE DATE(timestamp) >= DATE('now', '-56 days')
        GROUP BY STRFTIME('%Y-W%W', timestamp)
        ORDER BY period DESC
        """
    ).fetchall()
    weekly = [
        {
            "period":        r["period"],
            "call_count":    r["call_count"],
            "input_tokens":  r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "cost_usd":      round(r["cost_usd"], 6),
        }
        for r in weekly_rows
    ]

    # -----------------------------------------------------------------------
    # Monthly — last 12 months
    # -----------------------------------------------------------------------
    monthly_rows = db.execute(
        """
        SELECT
            STRFTIME('%Y-%m', timestamp) AS period,
            COUNT(*)             AS call_count,
            SUM(input_tokens)    AS input_tokens,
            SUM(output_tokens)   AS output_tokens,
            SUM(cost_usd)        AS cost_usd
        FROM claude_usage_log
        WHERE DATE(timestamp) >= DATE('now', '-365 days')
        GROUP BY STRFTIME('%Y-%m', timestamp)
        ORDER BY period DESC
        """
    ).fetchall()
    monthly = [
        {
            "period":        r["period"],
            "call_count":    r["call_count"],
            "input_tokens":  r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "cost_usd":      round(r["cost_usd"], 6),
        }
        for r in monthly_rows
    ]

    # -----------------------------------------------------------------------
    # By feature
    # -----------------------------------------------------------------------
    feature_rows = db.execute(
        """
        SELECT
            feature,
            COUNT(*)             AS call_count,
            SUM(input_tokens)    AS input_tokens,
            SUM(output_tokens)   AS output_tokens,
            SUM(cost_usd)        AS cost_usd
        FROM claude_usage_log
        GROUP BY feature
        ORDER BY cost_usd DESC
        """
    ).fetchall()
    by_feature = [
        {
            "feature":       r["feature"],
            "call_count":    r["call_count"],
            "input_tokens":  r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "cost_usd":      round(r["cost_usd"], 6),
        }
        for r in feature_rows
    ]

    return {
        "all_time":   all_time,
        "daily":      daily,
        "weekly":     weekly,
        "monthly":    monthly,
        "by_feature": by_feature,
    }
