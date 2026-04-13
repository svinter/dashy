"""Add amazon_url to library_entries

Revision ID: 20260413_0001
Revises: 20260412_0001
Create Date: 2026-04-13 00:01:00

amazon_url is a search/display field on library_entries, not book-specific.
Stored alongside url and webpage_url on the master entry row.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260413_0001"
down_revision: Union[str, None] = "20260412_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE library_entries ADD COLUMN amazon_url TEXT"
    )

    # Seed library_topics with the codes referenced in the design document.
    # Note: the design doc deferred the full list ("To be provided by Steve").
    # The codes below are those explicitly mentioned in §3.3 and §4.2 examples.
    # Extend this list once the full taxonomy is confirmed.
    op.execute("""
        INSERT OR IGNORE INTO library_topics (code, name) VALUES
            ('co', 'communication'),
            ('le', 'leadership'),
            ('en', 'enneagram'),
            ('od', 'organizational development'),
            ('cc', 'coaching craft'),
            ('pm', 'productivity & mindset'),
            ('st', 'strategy'),
            ('te', 'team effectiveness'),
            ('cx', 'culture & change')
    """)


def downgrade() -> None:
    # SQLite cannot drop columns; remove the seeded topics only.
    op.execute("""
        DELETE FROM library_topics
        WHERE code IN ('co','le','en','od','cc','pm','st','te','cx')
    """)
