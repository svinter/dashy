"""Add glance_gcal_imports table for idempotent GCal → Glance imports.

Revision ID: 20260423_0002
Revises: 20260423_0001
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa

revision = '20260423_0002'
down_revision = '20260423_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'glance_gcal_imports',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column('gcal_event_id', sa.Text(), nullable=False, unique=True),
        sa.Column('imported_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('target_type', sa.Text(), nullable=False),   # 'entry' or 'trip'
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('parse_result', sa.Text(), nullable=True),   # JSON summary
        sa.Column('deleted_from_gcal', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade():
    op.drop_table('glance_gcal_imports')
