"""Add email column to billing_clients

Revision ID: 20260411_0002
Revises: 20260411_0001
Create Date: 2026-04-11 00:02:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260411_0002"
down_revision: Union[str, None] = "20260411_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE billing_clients ADD COLUMN email TEXT")


def downgrade() -> None:
    pass
