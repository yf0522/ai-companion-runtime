"""add production care and notification contracts

Revision ID: f6a7b8c9d0e1
Revises: d4e5f6a7b8c9
Create Date: 2026-07-10 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reminders", sa.Column("lease_until", sa.DateTime(), nullable=True))
    op.add_column("reminders", sa.Column("lease_owner", sa.String(), nullable=True))
    op.add_column("reminders", sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False))

    op.add_column("care_tasks", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("care_tasks", sa.Column("idempotency_key", sa.String(), nullable=True))
    op.create_index("idx_care_tasks_user_idempotency", "care_tasks", ["user_id", "idempotency_key"], unique=True)

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("response_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status_code", sa.Integer(), server_default="200", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "key", "operation", name="uq_idempotency_user_key_operation"),
    )
    op.create_index("idx_idempotency_records_user", "idempotency_records", ["user_id", "created_at"], unique=False)

    op.create_table(
        "reminder_delivery_attempts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("reminder_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("state", sa.String(), server_default="queued", nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("provider_message_id", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("device_received_at", sa.DateTime(), nullable=True),
        sa.Column("played_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("expired_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["reminder_id"], ["reminders.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_reminder_delivery_attempt_idempotency"),
    )
    op.create_index(
        "idx_reminder_delivery_attempts_reminder",
        "reminder_delivery_attempts",
        ["reminder_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_reminder_delivery_attempts_state",
        "reminder_delivery_attempts",
        ["state", "due_at"],
        unique=False,
    )

    op.create_table(
        "safety_decisions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("risk_level", sa.String(), nullable=False),
        sa.Column("risk_category", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("evidence_ref", sa.String(), nullable=True),
        sa.Column("evidence_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("calibration", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_safety_decisions_user", "safety_decisions", ["user_id", "created_at"], unique=False)
    op.create_index("idx_safety_decisions_trace", "safety_decisions", ["trace_id"], unique=False)

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("safety_decision_id", sa.UUID(), nullable=True),
        sa.Column("contact_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(), server_default="sandbox", nullable=False),
        sa.Column("channel", sa.String(), server_default="webhook", nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("state", sa.String(), server_default="queued", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("provider_message_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["safety_decision_id"], ["safety_decisions.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["emergency_contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_notification_outbox_idempotency"),
    )
    op.create_index("idx_notification_outbox_state", "notification_outbox", ["state", "next_attempt_at"], unique=False)
    op.create_index("idx_notification_outbox_user", "notification_outbox", ["user_id", "created_at"], unique=False)

    op.create_table(
        "notification_receipts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("outbox_id", sa.UUID(), nullable=False),
        sa.Column("provider_message_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["outbox_id"], ["notification_outbox.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_notification_receipts_outbox", "notification_receipts", ["outbox_id", "created_at"], unique=False)

    op.create_table(
        "operator_cases",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("safety_decision_id", sa.UUID(), nullable=True),
        sa.Column("notification_outbox_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(), server_default="open", nullable=False),
        sa.Column("severity", sa.String(), server_default="high", nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["safety_decision_id"], ["safety_decisions.id"]),
        sa.ForeignKeyConstraint(["notification_outbox_id"], ["notification_outbox.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_operator_cases_status", "operator_cases", ["status", "severity", "created_at"], unique=False)
    op.create_index("idx_operator_cases_user", "operator_cases", ["user_id", "created_at"], unique=False)

    op.add_column("notification_log", sa.Column("safety_decision_id", sa.UUID(), nullable=True))
    op.add_column("notification_log", sa.Column("outbox_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_notification_log_safety_decision",
        "notification_log",
        "safety_decisions",
        ["safety_decision_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_notification_log_outbox",
        "notification_log",
        "notification_outbox",
        ["outbox_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_notification_log_outbox", "notification_log", type_="foreignkey")
    op.drop_constraint("fk_notification_log_safety_decision", "notification_log", type_="foreignkey")
    op.drop_column("notification_log", "outbox_id")
    op.drop_column("notification_log", "safety_decision_id")
    op.drop_index("idx_operator_cases_user", table_name="operator_cases")
    op.drop_index("idx_operator_cases_status", table_name="operator_cases")
    op.drop_table("operator_cases")
    op.drop_index("idx_notification_receipts_outbox", table_name="notification_receipts")
    op.drop_table("notification_receipts")
    op.drop_index("idx_notification_outbox_user", table_name="notification_outbox")
    op.drop_index("idx_notification_outbox_state", table_name="notification_outbox")
    op.drop_table("notification_outbox")
    op.drop_index("idx_safety_decisions_trace", table_name="safety_decisions")
    op.drop_index("idx_safety_decisions_user", table_name="safety_decisions")
    op.drop_table("safety_decisions")
    op.drop_index("idx_reminder_delivery_attempts_state", table_name="reminder_delivery_attempts")
    op.drop_index("idx_reminder_delivery_attempts_reminder", table_name="reminder_delivery_attempts")
    op.drop_table("reminder_delivery_attempts")
    op.drop_index("idx_idempotency_records_user", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("idx_care_tasks_user_idempotency", table_name="care_tasks")
    op.drop_column("care_tasks", "idempotency_key")
    op.drop_column("care_tasks", "version")
    op.drop_column("reminders", "retry_count")
    op.drop_column("reminders", "lease_owner")
    op.drop_column("reminders", "lease_until")
