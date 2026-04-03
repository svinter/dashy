"""Add email_subject/email_body to billing_companies; sent_at to billing_invoices

Revision ID: 20260403_0001
Revises: 20260402_0002
Create Date: 2026-04-03 00:01:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260403_0001"
down_revision: Union[str, None] = "20260402_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE billing_companies ADD COLUMN email_subject TEXT")
    op.execute("ALTER TABLE billing_companies ADD COLUMN email_body TEXT")
    op.execute("ALTER TABLE billing_invoices ADD COLUMN sent_at TEXT")


def downgrade() -> None:
    pass  # SQLite can't drop columns
