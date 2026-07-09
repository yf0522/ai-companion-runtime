from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(nullable=False)
    display_name: Mapped[str | None] = mapped_column()
    status: Mapped[str] = mapped_column(nullable=False, default="enrolled")
    credential_state: Mapped[str] = mapped_column(nullable=False, default="active")
    credential_hash: Mapped[str] = mapped_column(nullable=False)
    capabilities_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    firmware_version: Mapped[str | None] = mapped_column()
    last_heartbeat_at: Mapped[datetime | None] = mapped_column()
    last_health_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    revoked_at: Mapped[datetime | None] = mapped_column()
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    sequence_high_watermark: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("external_id", name="uq_devices_external_id"),
        Index("idx_devices_user_status", "user_id", "status"),
    )


class DeviceEnrollmentCredential(Base):
    __tablename__ = "device_enrollment_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    secret_hash: Mapped[str] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(nullable=False, default="issued")
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_by_device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("devices.id"))
    used_at: Mapped[datetime | None] = mapped_column()
    revoked_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (Index("idx_device_enrollment_state", "user_id", "state"),)


class DeviceCommandReceipt(Base):
    __tablename__ = "device_command_receipts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False)
    command_id: Mapped[str] = mapped_column(nullable=False)
    receipt_type: Mapped[str] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("device_id", "command_id", "receipt_type", name="uq_device_command_receipt"),
        Index("idx_device_command_receipts_device", "device_id", "created_at"),
    )


class DeviceOtaRelease(Base):
    __tablename__ = "device_ota_releases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    version: Mapped[str] = mapped_column(nullable=False)
    artifact_url: Mapped[str] = mapped_column(nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(nullable=False)
    signature: Mapped[str | None] = mapped_column(Text)
    signing_key_id: Mapped[str | None] = mapped_column()
    verification_state: Mapped[str] = mapped_column(nullable=False, default="pending_evidence")
    pending_evidence: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (UniqueConstraint("version", name="uq_device_ota_releases_version"),)


class DeviceOtaAssignment(Base):
    __tablename__ = "device_ota_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False)
    release_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("device_ota_releases.id"), nullable=False)
    state: Mapped[str] = mapped_column(nullable=False, default="pending")
    last_receipt_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("device_id", "release_id", name="uq_device_ota_assignment"),
        Index("idx_device_ota_assignments_device", "device_id", "state"),
    )
