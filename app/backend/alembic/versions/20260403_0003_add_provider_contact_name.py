"""Add provider_contact_name to billing_provider_settings

Revision ID: 20260403_0003
Revises: 20260403_0002
Create Date: 2026-04-03 00:03:00

Stores the individual's name (e.g. "Steve Vinter") separately from
provider_name (the company name "Vantage Insights") so the PDF header
can display both and the email signature can use the personal name.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260403_0003"
down_revision: Union[str, None] = "20260403_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE billing_provider_settings ADD COLUMN provider_contact_name TEXT NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    pass  # SQLite can't drop columns
