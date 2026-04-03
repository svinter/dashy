"""Add billing_* tables

Revision ID: 20260401_0001
Revises: 20260401_0000
Create Date: 2026-04-01 00:01:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260401_0001"
down_revision: Union[str, None] = "20260401_0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_companies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            abbrev          TEXT,
            default_rate    REAL,
            billing_method  TEXT,
            payment_method  TEXT,
            ap_email        TEXT,
            cc_email        TEXT,
            tax_tool        TEXT,
            invoice_prefix  TEXT,
            notes           TEXT,
            active          BOOLEAN NOT NULL DEFAULT 1
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_clients (
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

    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_invoices (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number      TEXT UNIQUE NOT NULL,
            company_id          INTEGER REFERENCES billing_companies(id),
            period_month        TEXT,
            invoice_date        DATE,
            services_date       DATE,
            due_date            DATE,
            status              TEXT NOT NULL DEFAULT 'draft',
            total_amount        REAL,
            pdf_path            TEXT,
            receipt_pdf_path    TEXT,
            notes               TEXT,
            created_at          DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_invoice_lines (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id  INTEGER NOT NULL REFERENCES billing_invoices(id),
            type        TEXT NOT NULL,
            description TEXT,
            date_range  TEXT,
            unit_cost   REAL,
            quantity    REAL,
            amount      REAL,
            sort_order  INTEGER
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_prepaid_blocks (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id            INTEGER NOT NULL REFERENCES billing_clients(id),
            sessions_purchased   INTEGER NOT NULL,
            starting_after_date  DATE,
            invoice_id           INTEGER REFERENCES billing_invoices(id),
            created_at           DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_sessions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            date                DATE,
            client_id           INTEGER REFERENCES billing_clients(id),
            company_id          INTEGER REFERENCES billing_companies(id),
            duration_hours      REAL,
            rate                REAL,
            amount              REAL,
            is_confirmed        BOOLEAN NOT NULL DEFAULT 0,
            prepaid_block_id    INTEGER REFERENCES billing_prepaid_blocks(id),
            calendar_event_id   TEXT,
            color_id            TEXT,
            obsidian_note_path  TEXT,
            notes               TEXT,
            invoice_line_id     INTEGER REFERENCES billing_invoice_lines(id),
            created_at          DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_payments (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            lunchmoney_transaction_id   INTEGER UNIQUE,
            date                        DATE,
            amount                      REAL,
            payee                       TEXT,
            notes                       TEXT,
            created_at                  DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_invoice_payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id      INTEGER NOT NULL REFERENCES billing_invoices(id),
            payment_id      INTEGER NOT NULL REFERENCES billing_payments(id),
            amount_applied  REAL NOT NULL
        )
    """)


def downgrade() -> None:
    # Drop in reverse dependency order
    op.execute("DROP TABLE IF EXISTS billing_invoice_payments")
    op.execute("DROP TABLE IF EXISTS billing_payments")
    op.execute("DROP TABLE IF EXISTS billing_sessions")
    op.execute("DROP TABLE IF EXISTS billing_prepaid_blocks")
    op.execute("DROP TABLE IF EXISTS billing_invoice_lines")
    op.execute("DROP TABLE IF EXISTS billing_invoices")
    op.execute("DROP TABLE IF EXISTS billing_clients")
    op.execute("DROP TABLE IF EXISTS billing_companies")
