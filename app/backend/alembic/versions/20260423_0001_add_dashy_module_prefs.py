"""Add dashy_module_prefs table for sidebar visibility preferences.

Revision ID: 20260423_0001
Revises: 20260422_0002
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa

revision = '20260423_0001'
down_revision = '20260422_0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'dashy_module_prefs',
        sa.Column('module_id', sa.Text(), nullable=False, primary_key=True),
        sa.Column('visible', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP')),
    )


def downgrade():
    op.drop_table('dashy_module_prefs')
