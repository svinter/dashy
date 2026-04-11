"""Add billing_projects table and project_id to billing_sessions

Revision ID: 20260411_0001
Revises: 20260410_0001
Create Date: 2026-04-11 00:01:00

Spec: ~/Obsidian/MyNotes/Projects/Dashy/projects_spec.md § 2.1–2.2

New table billing_projects:
  - one project belongs to exactly one company
  - billing_type: 'hourly' | 'fixed'
  - fixed_amount: total charge for fixed-rate projects (null if hourly)
  - rate_override: per-project hourly rate (null → use company default_rate)
  - obsidian_name: exact filename token used in 8 Meetings/ notes

Modified table billing_sessions:
  - project_id: FK → billing_projects.id (nullable)
  - Invariant: confirmed sessions have client_id OR project_id, never both/neither
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260411_0001"
down_revision: Union[str, None] = "20260410_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_projects (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            name                    TEXT    NOT NULL,
            company_id              INTEGER NOT NULL REFERENCES billing_companies(id),
            billing_type            TEXT    NOT NULL DEFAULT 'hourly',
            fixed_amount            REAL,
            rate_override           REAL,
            obsidian_name           TEXT,
            gdrive_folder_url       TEXT,
            gdrive_coaching_docs_url TEXT,
            active                  BOOLEAN NOT NULL DEFAULT 1
        )
    """)

    op.execute(
        "ALTER TABLE billing_sessions ADD COLUMN project_id INTEGER REFERENCES billing_projects(id)"
    )


def downgrade() -> None:
    # SQLite cannot drop columns or tables with active FKs cleanly; no-op.
    pass
