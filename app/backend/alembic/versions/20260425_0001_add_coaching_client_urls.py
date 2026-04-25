"""Add coaching_agreement_url and shared_notes_url to billing_clients.

Revision ID: 20260425_0001
Revises: 20260424_0004
Create Date: 2026-04-25
"""

from alembic import op

revision = '20260425_0001'
down_revision = '20260424_0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE billing_clients ADD COLUMN coaching_agreement_url TEXT")
    op.execute("ALTER TABLE billing_clients ADD COLUMN shared_notes_url TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE billing_clients DROP COLUMN coaching_agreement_url")
    op.execute("ALTER TABLE billing_clients DROP COLUMN shared_notes_url")
