"""Add claude_usage_log table for API cost tracking.

Revision ID: 20260425_0002
Revises: 20260425_0001
Create Date: 2026-04-25
"""

from alembic import op

revision = '20260425_0002'
down_revision = '20260425_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS claude_usage_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT NOT NULL DEFAULT (datetime('now')),
            feature       TEXT NOT NULL,
            input_tokens  INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd      REAL NOT NULL DEFAULT 0.0,
            model         TEXT NOT NULL,
            notes         TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claude_usage_timestamp ON claude_usage_log(timestamp)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claude_usage_feature ON claude_usage_log(feature)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS claude_usage_log")
