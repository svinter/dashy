"""Add manifest_gdoc_url to billing_clients

Revision ID: 20260413_0004
Revises: 20260413_0003
Create Date: 2026-04-13 00:04:00

manifest_gdoc_url stores the Google Doc URL for the client's coaching
manifest. Set during client creation via the Setup page, and retroactively
for existing clients in a separate step.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260413_0004"
down_revision: Union[str, None] = "20260413_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE billing_clients ADD COLUMN manifest_gdoc_url TEXT")


def downgrade() -> None:
    # SQLite cannot drop columns; no-op.
    pass
