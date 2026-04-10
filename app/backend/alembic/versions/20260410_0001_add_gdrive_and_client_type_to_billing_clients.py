"""Add client_type, gdrive_folder_url, gdrive_coaching_docs_url to billing_clients

Revision ID: 20260410_0001
Revises: 20260405_0002
Create Date: 2026-04-10 00:01:00

"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260410_0001"
down_revision: Union[str, None] = "20260405_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE billing_clients ADD COLUMN client_type TEXT")
    op.execute("ALTER TABLE billing_clients ADD COLUMN gdrive_folder_url TEXT")
    op.execute("ALTER TABLE billing_clients ADD COLUMN gdrive_coaching_docs_url TEXT")


def downgrade() -> None:
    pass  # SQLite can't drop columns
