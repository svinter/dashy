"""Add canceled column to billing_sessions

Revision ID: 20260424_0003
Revises: 20260424_0002
Create Date: 2026-04-24
"""

from alembic import op

revision = "20260424_0003"
down_revision = "20260423_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE billing_sessions ADD COLUMN canceled BOOLEAN NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE billing_sessions DROP COLUMN canceled")
