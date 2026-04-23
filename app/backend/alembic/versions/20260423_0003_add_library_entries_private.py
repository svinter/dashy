"""Add private column to library_entries

Revision ID: 20260423_0003
Revises: 20260424_0002
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "20260423_0003"
down_revision = "20260424_0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("library_entries") as batch_op:
        batch_op.add_column(sa.Column("private", sa.Boolean(), nullable=False, server_default="0"))


def downgrade():
    pass  # no-op — SQLite doesn't support DROP COLUMN easily
