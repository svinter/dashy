"""Add gdrive_folder_url to billing_companies

Revision ID: 20260413_0003
Revises: 20260413_0002
Create Date: 2026-04-13 00:03:00

Stores the Google Drive top-level folder URL for each company,
managed by the Setup page after initial folder creation.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260413_0003"
down_revision: Union[str, None] = "20260413_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE billing_companies ADD COLUMN gdrive_folder_url TEXT")


def downgrade() -> None:
    # SQLite cannot drop columns; no-op.
    pass
