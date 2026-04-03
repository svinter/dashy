"""Add company_id FK to billing_payments

Revision ID: 20260402_0001
Revises: 20260401_0003
Create Date: 2026-04-02 00:01:00

Allows payments to be associated with a company without requiring an invoice,
enabling pre-Dashy payments to appear correctly in Cash Received tax reporting.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260402_0001"
down_revision: Union[str, None] = "20260401_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE billing_payments ADD COLUMN company_id INTEGER REFERENCES billing_companies(id)"
    )


def downgrade() -> None:
    pass  # SQLite can't drop columns
