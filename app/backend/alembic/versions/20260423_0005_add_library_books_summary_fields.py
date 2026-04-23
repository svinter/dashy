"""Add gdoc_summary_id and external_summary_url to library_books

Revision ID: 20260423_0005
Revises: 20260423_0004
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "20260423_0005"
down_revision = "20260423_0004"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("library_books") as batch_op:
        batch_op.add_column(sa.Column("gdoc_summary_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("external_summary_url", sa.Text(), nullable=True))


def downgrade():
    pass  # no-op
