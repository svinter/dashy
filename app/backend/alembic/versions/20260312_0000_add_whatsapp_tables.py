"""Add whatsapp_conversations and whatsapp_messages tables

Revision ID: 20260312_0000
Revises: 20260311_0000
Create Date: 2026-03-12 00:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260312_0000"
down_revision: Union[str, None] = "20260311_0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS whatsapp_conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone_number TEXT NOT NULL UNIQUE,
        created_at TEXT DEFAULT (datetime('now')),
        last_message_at TEXT DEFAULT (datetime('now'))
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS whatsapp_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content TEXT NOT NULL DEFAULT '',
        whatsapp_message_id TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (conversation_id) REFERENCES whatsapp_conversations(id) ON DELETE CASCADE
    )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_wa_messages_conv ON whatsapp_messages(conversation_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS whatsapp_messages")
    op.execute("DROP TABLE IF EXISTS whatsapp_conversations")
