"""Add highlights_path column to library_books

Revision ID: 20260423_0004
Revises: 20260424_0003
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "20260423_0004"
down_revision = "20260424_0003"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("library_books") as batch_op:
        batch_op.add_column(sa.Column("highlights_path", sa.Text(), nullable=True))


def downgrade():
    pass  # no-op
