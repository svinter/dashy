"""Add payment_instructions to billing_companies

Revision ID: 20260402_0002
Revises: 20260402_0001
Create Date: 2026-04-02 00:02:00

Moves per-company payment instructions from hardcoded PDF logic into the DB,
and adds invoice_output_dir + provider fields to support configurable PDF generation.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260402_0002"
down_revision: Union[str, None] = "20260402_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE billing_companies ADD COLUMN payment_instructions TEXT"
    )


def downgrade() -> None:
    pass  # SQLite can't drop columns
