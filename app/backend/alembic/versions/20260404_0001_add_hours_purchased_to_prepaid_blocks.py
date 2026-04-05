"""Add hours_purchased to billing_prepaid_blocks, make sessions_purchased optional

Revision ID: 20260404_0001
Revises: 20260403_0003
Create Date: 2026-04-04 00:01:00

Adds hours_purchased (REAL) as the primary unit of prepaid block capacity.
sessions_purchased is kept for reference but is now nullable.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260404_0001"
down_revision: Union[str, None] = "20260403_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite can't alter column constraints, so recreate the table.
    # New schema: sessions_purchased nullable, hours_purchased REAL added.
    op.execute("""
        CREATE TABLE billing_prepaid_blocks_new (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id            INTEGER NOT NULL REFERENCES billing_clients(id),
            sessions_purchased   INTEGER,
            hours_purchased      REAL,
            starting_after_date  DATE,
            invoice_id           INTEGER REFERENCES billing_invoices(id),
            created_at           DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute("""
        INSERT INTO billing_prepaid_blocks_new
            (id, client_id, sessions_purchased, hours_purchased,
             starting_after_date, invoice_id, created_at)
        SELECT id, client_id, sessions_purchased, NULL,
               starting_after_date, invoice_id, created_at
        FROM billing_prepaid_blocks
    """)
    op.execute("DROP TABLE billing_prepaid_blocks")
    op.execute(
        "ALTER TABLE billing_prepaid_blocks_new RENAME TO billing_prepaid_blocks"
    )


def downgrade() -> None:
    op.execute("""
        CREATE TABLE billing_prepaid_blocks_old (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id            INTEGER NOT NULL REFERENCES billing_clients(id),
            sessions_purchased   INTEGER NOT NULL DEFAULT 0,
            starting_after_date  DATE,
            invoice_id           INTEGER REFERENCES billing_invoices(id),
            created_at           DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute("""
        INSERT INTO billing_prepaid_blocks_old
            (id, client_id, sessions_purchased, starting_after_date, invoice_id, created_at)
        SELECT id, client_id, COALESCE(sessions_purchased, 0),
               starting_after_date, invoice_id, created_at
        FROM billing_prepaid_blocks
    """)
    op.execute("DROP TABLE billing_prepaid_blocks")
    op.execute(
        "ALTER TABLE billing_prepaid_blocks_old RENAME TO billing_prepaid_blocks"
    )
