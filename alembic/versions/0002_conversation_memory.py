"""Persistent ordered memory, summaries and privacy-limited tool audit metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_memory"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute("""UPDATE conversations c SET last_activity_at = GREATEST(c.updated_at,
        COALESCE((SELECT MAX(m.created_at) FROM messages m WHERE m.conversation_id = c.id),
                 c.created_at))""")
    op.add_column(
        "conversations",
        sa.Column("memory_summary", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "conversations",
        sa.Column("summary_through_sequence", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "summary_cursor_nonnegative", "conversations", "summary_through_sequence >= 0"
    )
    op.create_index(
        "ix_conversations_customer_activity",
        "conversations",
        ["customer_id", "last_activity_at", "id"],
    )
    op.create_index("ix_conversations_last_activity_at", "conversations", ["last_activity_at"])
    op.add_column("messages", sa.Column("sequence", sa.BigInteger(), nullable=True))
    # Preserve existing timestamp order before enabling a durable identity sequence.
    op.execute("""WITH ordered AS (SELECT id, ROW_NUMBER() OVER (ORDER BY created_at, id) AS n
        FROM messages) UPDATE messages m SET sequence = ordered.n
        FROM ordered WHERE m.id = ordered.id""")
    op.alter_column("messages", "sequence", nullable=False)
    op.execute("ALTER TABLE messages ALTER COLUMN sequence ADD GENERATED ALWAYS AS IDENTITY")
    op.execute("""SELECT setval(pg_get_serial_sequence('messages', 'sequence'),
        GREATEST(COALESCE(MAX(sequence), 0), 1), COUNT(*) > 0) FROM messages""")
    op.add_column(
        "messages",
        sa.Column("metadata_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index(
        "ix_messages_conversation_sequence",
        "messages",
        ["conversation_id", "sequence"],
        unique=True,
    )
    op.create_index("ix_messages_created_at", "messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_messages_created_at", table_name="messages")
    op.drop_index("ix_messages_conversation_sequence", table_name="messages")
    op.drop_column("messages", "metadata_json")
    op.drop_column("messages", "sequence")
    op.drop_index("ix_conversations_last_activity_at", table_name="conversations")
    op.drop_index("ix_conversations_customer_activity", table_name="conversations")
    op.drop_constraint(
        op.f("ck_conversations_summary_cursor_nonnegative"), "conversations", type_="check"
    )
    op.drop_column("conversations", "summary_through_sequence")
    op.drop_column("conversations", "memory_summary")
    op.drop_column("conversations", "last_activity_at")
