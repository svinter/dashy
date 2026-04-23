"""Add digest_runs table to store daily digest history.

Revision ID: 20260424_0001
Revises: 20260423_0002
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa

revision = '20260424_0001'
down_revision = '20260423_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS digest_runs (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date            DATE NOT NULL,
            sent_at             TIMESTAMP NOT NULL,
            today_sessions      JSON,
            tomorrow_sessions   JSON,
            note_creation       JSON,
            granola_sync        JSON,
            unprocessed_sessions JSON,
            backup_summary      JSON
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS digest_runs")
