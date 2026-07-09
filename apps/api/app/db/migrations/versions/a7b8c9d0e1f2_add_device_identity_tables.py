"""add device identity tables

Revision ID: a7b8c9d0e1f2
Revises: d4e5f6a7b8c9
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="enrolled"),
        sa.Column("credential_state", sa.String(), nullable=False, server_default="active"),
        sa.Column("credential_hash", sa.String(), nullable=False),
        sa.Column("capabilities_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("firmware_version", sa.String(), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("last_health_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("sequence_high_watermark", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", name="uq_devices_external_id"),
    )
    op.create_index("idx_devices_user_status", "devices", ["user_id", "status"], unique=False)
    op.create_table(
        "device_enrollment_credentials",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("secret_hash", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="issued"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_by_device_id", sa.UUID(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["used_by_device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_device_enrollment_state", "device_enrollment_credentials", ["user_id", "state"], unique=False)
    op.create_table(
        "device_command_receipts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("device_id", sa.UUID(), nullable=False),
        sa.Column("command_id", sa.String(), nullable=False),
        sa.Column("receipt_type", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "command_id", "receipt_type", name="uq_device_command_receipt"),
    )
    op.create_index("idx_device_command_receipts_device", "device_command_receipts", ["device_id", "created_at"], unique=False)
    op.create_table(
        "device_ota_releases",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("artifact_url", sa.String(), nullable=False),
        sa.Column("artifact_sha256", sa.String(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("signing_key_id", sa.String(), nullable=True),
        sa.Column("verification_state", sa.String(), nullable=False, server_default="pending_evidence"),
        sa.Column("pending_evidence", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version", name="uq_device_ota_releases_version"),
    )
    op.create_table(
        "device_ota_assignments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("device_id", sa.UUID(), nullable=False),
        sa.Column("release_id", sa.UUID(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="pending"),
        sa.Column("last_receipt_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["release_id"], ["device_ota_releases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "release_id", name="uq_device_ota_assignment"),
    )
    op.create_index("idx_device_ota_assignments_device", "device_ota_assignments", ["device_id", "state"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_device_ota_assignments_device", table_name="device_ota_assignments")
    op.drop_table("device_ota_assignments")
    op.drop_table("device_ota_releases")
    op.drop_index("idx_device_command_receipts_device", table_name="device_command_receipts")
    op.drop_table("device_command_receipts")
    op.drop_index("idx_device_enrollment_state", table_name="device_enrollment_credentials")
    op.drop_table("device_enrollment_credentials")
    op.drop_index("idx_devices_user_status", table_name="devices")
    op.drop_table("devices")
