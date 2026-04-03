"""Add billing_provider_settings table (single-row provider contact info)

Revision ID: 20260403_0002
Revises: 20260403_0001
Create Date: 2026-04-03 00:02:00

Moves provider identity (name, address, phone, email) from config.json into
the database so it can be managed alongside other billing data and imported
via the seed file.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260403_0002"
down_revision: Union[str, None] = "20260403_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_provider_settings (
            id                   INTEGER PRIMARY KEY CHECK (id = 1),
            provider_name        TEXT NOT NULL DEFAULT '',
            provider_address1    TEXT NOT NULL DEFAULT '',
            provider_address2    TEXT NOT NULL DEFAULT '',
            provider_city_state_zip TEXT NOT NULL DEFAULT '',
            provider_phone       TEXT NOT NULL DEFAULT '',
            provider_email       TEXT NOT NULL DEFAULT ''
        )
    """)
    # Ensure the single row exists
    op.execute(
        "INSERT OR IGNORE INTO billing_provider_settings (id) VALUES (1)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS billing_provider_settings")
