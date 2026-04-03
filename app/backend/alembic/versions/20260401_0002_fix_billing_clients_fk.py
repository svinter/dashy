"""Fix billing_clients employee_id FK: employees → people

Revision ID: 20260401_0002
Revises: 20260401_0001
Create Date: 2026-04-01 00:02:00

SQLite enforces FK parent-table existence when foreign_keys=ON.
The billing_clients table was created with REFERENCES employees(id)
but the actual table in this codebase is named 'people'.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260401_0002"
down_revision: Union[str, None] = "20260401_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Recreate billing_clients with correct FK (people instead of employees).
    # Table is empty at this point so no data migration needed.
    op.execute("DROP TABLE IF EXISTS billing_clients")
    op.execute("""
        CREATE TABLE billing_clients (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            company_id      INTEGER REFERENCES billing_companies(id),
            rate_override   REAL,
            prepaid         BOOLEAN NOT NULL DEFAULT 0,
            obsidian_name   TEXT,
            employee_id     INTEGER REFERENCES people(id),
            active          BOOLEAN NOT NULL DEFAULT 1
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS billing_clients")
    op.execute("""
        CREATE TABLE billing_clients (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            company_id      INTEGER REFERENCES billing_companies(id),
            rate_override   REAL,
            prepaid         BOOLEAN NOT NULL DEFAULT 0,
            obsidian_name   TEXT,
            employee_id     INTEGER REFERENCES employees(id),
            active          BOOLEAN NOT NULL DEFAULT 1
        )
    """)
