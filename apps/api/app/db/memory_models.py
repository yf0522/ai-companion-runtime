from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class MemoryConsentGrant(Base):
    __tablename__ = "memory_consent_grants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    purpose: Mapped[str] = mapped_column(nullable=False)
    scope_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    sensitivity_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    retention_days: Mapped[int | None] = mapped_column()
    consent_version: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="granted")
    granted_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    expires_at: Mapped[datetime | None] = mapped_column()
    revoked_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        Index("idx_memory_consent_user_purpose", "user_id", "purpose", "status"),
    )


class MemoryCorrectionEvent(Base):
    __tablename__ = "memory_correction_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("memories.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    original_content: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_content: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(nullable=False, default="applied")
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    applied_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        Index("idx_memory_correction_memory", "memory_id", "created_at"),
    )


class ReflectionProposal(Base):
    __tablename__ = "memory_reflection_proposals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sessions.id"))
    target_type: Mapped[str] = mapped_column(nullable=False)
    proposed_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    policy_version: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="proposed")
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    accepted_at: Mapped[datetime | None] = mapped_column()
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        Index("idx_memory_reflection_user_status", "user_id", "status", "created_at"),
    )
