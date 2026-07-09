"""add notification outbox leases and receipt identity

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-10 04:10:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notification_outbox", sa.Column("attempt_identity", sa.String(), nullable=True))
    op.add_column("notification_outbox", sa.Column("lease_owner", sa.String(), nullable=True))
    op.add_column("notification_outbox", sa.Column("lease_until", sa.DateTime(), nullable=True))
    op.create_index(
        "idx_notification_outbox_lease",
        "notification_outbox",
        ["state", "lease_until"],
        unique=False,
    )

    op.add_column("notification_receipts", sa.Column("receipt_identity", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE notification_receipts
        SET receipt_identity =
            event_type || ':' || COALESCE(provider_message_id, id::text)
        WHERE receipt_identity IS NULL
        """
    )
    op.create_unique_constraint(
        "uq_notification_receipts_identity",
        "notification_receipts",
        ["outbox_id", "receipt_identity"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_notification_receipts_identity", "notification_receipts", type_="unique")
    op.drop_column("notification_receipts", "receipt_identity")
    op.drop_index("idx_notification_outbox_lease", table_name="notification_outbox")
    op.drop_column("notification_outbox", "lease_until")
    op.drop_column("notification_outbox", "lease_owner")
    op.drop_column("notification_outbox", "attempt_identity")
