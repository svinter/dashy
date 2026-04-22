"""Add travel_color_bg/text to glance_members; fix location and member colors.

Revision ID: 20260422_0001
Revises: 20260421_0003
Create Date: 2026-04-22 00:01:00

Changes:
  - Add travel_color_bg, travel_color_text columns to glance_members
  - Update member event colors (color_bg/color_text) to correct values
  - Set travel colors for pgv, kpv, ovinters
  - Fix location colors: boston, york, sark to correct values
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260422_0001"
down_revision: Union[str, None] = "20260421_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add travel color columns to glance_members
    op.execute("ALTER TABLE glance_members ADD COLUMN travel_color_bg TEXT")
    op.execute("ALTER TABLE glance_members ADD COLUMN travel_color_text TEXT")

    # Update member event colors (color_bg / color_text) and set travel colors
    op.execute("""
        UPDATE glance_members SET
            color_bg = '#F3BFD2', color_text = '#72243E',
            travel_color_bg = '#F39EBD', travel_color_text = '#72243E'
        WHERE id = 'pgv'
    """)
    op.execute("""
        UPDATE glance_members SET
            color_bg = '#9DE1CA', color_text = '#085041',
            travel_color_bg = '#7CE1BF', travel_color_text = '#085041'
        WHERE id = 'kpv'
    """)
    op.execute("""
        UPDATE glance_members SET
            color_bg = '#FAC674', color_text = '#633806',
            travel_color_bg = '#FAAF38', travel_color_text = '#633806'
        WHERE id = 'ovinters'
    """)

    # Fix location colors
    op.execute("""
        UPDATE glance_locations SET color_bg = '#8CB8E5', color_text = '#042C53'
        WHERE id = 'boston'
    """)
    op.execute("""
        UPDATE glance_locations SET color_bg = '#97C35B', color_text = '#173404'
        WHERE id = 'york'
    """)
    op.execute("""
        UPDATE glance_locations SET color_bg = '#EF997A', color_text = '#4A1B0C'
        WHERE id = 'portugal'
    """)
    op.execute("""
        UPDATE glance_locations SET color_bg = '#EF997A', color_text = '#4A1B0C'
        WHERE id = 'azores'
    """)
    op.execute("""
        UPDATE glance_locations SET color_bg = '#EF997A', color_text = '#4A1B0C'
        WHERE id = 'sark'
    """)


def downgrade() -> None:
    pass  # SQLite does not support DROP COLUMN; color rollback not supported
