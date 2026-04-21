"""Add glance_week_comments table for per-week, per-lane comments.

Revision ID: 20260421_0002
Revises: 20260421_0001
Create Date: 2026-04-21 00:02:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260421_0002"
down_revision: Union[str, None] = "20260421_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS glance_week_comments (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          week_start  DATE NOT NULL,
          lane_id     TEXT NOT NULL,
          comment     TEXT NOT NULL DEFAULT '',
          created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_glance_week_comments
        ON glance_week_comments(week_start, lane_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_glance_week_comments")
    op.execute("DROP TABLE IF EXISTS glance_week_comments")
