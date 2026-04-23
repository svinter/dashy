"""Replace billing_clients.active (boolean) with status (tri-state text).

Revision ID: 20260424_0002
Revises: 20260424_0001
Create Date: 2026-04-24

Converts:
  active = 1  →  status = 'active'
  active = 0  →  status = 'inactive'
  (new value)  →  status = 'infrequent'
"""

from alembic import op

revision = '20260424_0002'
down_revision = '20260424_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the new status column
    op.execute("ALTER TABLE billing_clients ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    # Migrate existing values
    op.execute("UPDATE billing_clients SET status = CASE WHEN active = 1 THEN 'active' ELSE 'inactive' END")
    # Drop the old column (requires SQLite 3.35+, available in Python 3.11+)
    op.execute("ALTER TABLE billing_clients DROP COLUMN active")


def downgrade() -> None:
    op.execute("ALTER TABLE billing_clients ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    op.execute("UPDATE billing_clients SET active = CASE WHEN status = 'inactive' THEN 0 ELSE 1 END")
    op.execute("ALTER TABLE billing_clients DROP COLUMN status")
