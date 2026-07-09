"""add trace_id to notification_log

Revision ID: c2f3d1a9e7f4
Revises: b7c8d9e0f1a2
Create Date: 2026-07-09 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c2f3d1a9e7f4"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notification_log", sa.Column("trace_id", sa.String(), nullable=True))
    op.create_index("idx_notification_log_trace", "notification_log", ["trace_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_notification_log_trace", table_name="notification_log")
    op.drop_column("notification_log", "trace_id")
