"""make message order unique and trace lookup indexed

Revision ID: b0c1d2e3f4a5
Revises: a9c0d1e2f3b4
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, None] = "a9c0d1e2f3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        WITH ordered AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY session_id
                       ORDER BY message_index, created_at, id
                   ) - 1 AS new_index
            FROM messages
        )
        UPDATE messages AS m
        SET message_index = ordered.new_index
        FROM ordered
        WHERE m.id = ordered.id
          AND m.message_index IS DISTINCT FROM ordered.new_index
        """
    )
    op.drop_index("idx_messages_session", table_name="messages")
    op.create_unique_constraint(
        "uq_messages_session_message_index", "messages", ["session_id", "message_index"]
    )
    op.create_index("idx_messages_trace_id", "messages", ["trace_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_messages_trace_id", table_name="messages")
    op.drop_constraint("uq_messages_session_message_index", "messages", type_="unique")
    op.create_index(
        "idx_messages_session", "messages", ["session_id", "message_index"], unique=False
    )
