"""add idempotency claim state

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-10 04:20:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "idempotency_records",
        sa.Column(
            "error_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "idempotency_records",
        sa.Column("status", sa.String(), server_default="completed", nullable=False),
    )
    op.add_column(
        "idempotency_records",
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "idx_idempotency_records_status",
        "idempotency_records",
        ["status", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_idempotency_records_status", table_name="idempotency_records")
    op.drop_column("idempotency_records", "updated_at")
    op.drop_column("idempotency_records", "status")
    op.drop_column("idempotency_records", "error_json")
