"""Separate human acknowledgement from notification delivery state.

Revision ID: a9c0d1e2f3b4
Revises: f2a3b4c5d6e7
Create Date: 2026-07-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9c0d1e2f3b4"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notification_log", sa.Column("acknowledged_at", sa.DateTime(), nullable=True))
    op.add_column(
        "notification_log",
        sa.Column("acknowledged_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "notification_log",
        sa.Column("acknowledgement_actor_role", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_notification_log_acknowledged_by_user",
        "notification_log",
        "users",
        ["acknowledged_by_user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_notification_log_acknowledged_by_user",
        "notification_log",
        type_="foreignkey",
    )
    op.drop_column("notification_log", "acknowledgement_actor_role")
    op.drop_column("notification_log", "acknowledged_by_user_id")
    op.drop_column("notification_log", "acknowledged_at")
