from __future__ import annotations

import uuid
from datetime import datetime

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None
from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    username: Mapped[str] = mapped_column(unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(unique=True)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(default="elder")
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    sessions: Mapped[list[Session]] = relationship(back_populates="user")
    profile: Mapped[UserProfileModel | None] = relationship(back_populates="user")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(default="active")
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    last_active_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    message_count: Mapped[int] = mapped_column(default=0)
    metadata_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    user: Mapped[User] = relationship(back_populates="sessions")
    messages: Mapped[list[Message]] = relationship(back_populates="session")

    __table_args__ = (
        Index("idx_sessions_user", "user_id", "status"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_index: Mapped[int] = mapped_column(nullable=False)
    trace_id: Mapped[str | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    session: Mapped[Session] = relationship(back_populates="messages")

    __table_args__ = (
        Index("idx_messages_session", "session_id", "message_index"),
    )


class UserProfileModel(Base):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    profile_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    user: Mapped[User] = relationship(back_populates="profile")


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sessions.id"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    memory_type: Mapped[str] = mapped_column(nullable=False)
    importance_score: Mapped[float] = mapped_column(default=0.5)
    source_message_ids: Mapped[list | None] = mapped_column(ARRAY(UUID(as_uuid=True)))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    decayed_score: Mapped[float | None] = mapped_column()
    last_accessed_at: Mapped[datetime | None] = mapped_column()

    embedding: Mapped[MemoryEmbedding | None] = relationship(back_populates="memory")

    __table_args__ = (
        Index("idx_memories_user", "user_id", "importance_score"),
    )


class MemoryEmbedding(Base):
    __tablename__ = "memory_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    memory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("memories.id"), unique=True, nullable=False)
    embedding = mapped_column(Vector(1536)) if Vector else mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    memory: Mapped[Memory] = relationship(back_populates="embedding")


class TraceEvent(Base):
    __tablename__ = "trace_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    trace_id: Mapped[str] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column()
    session_id: Mapped[uuid.UUID | None] = mapped_column()
    step_name: Mapped[str] = mapped_column(nullable=False)
    step_index: Mapped[int | None] = mapped_column()
    input_json: Mapped[dict | None] = mapped_column(JSONB)
    output_json: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str | None] = mapped_column()
    error_message: Mapped[str | None] = mapped_column(Text)
    start_time: Mapped[datetime | None] = mapped_column()
    end_time: Mapped[datetime | None] = mapped_column()
    latency_ms: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        Index("idx_trace_events", "trace_id", "step_index"),
        Index("idx_trace_time", "created_at"),
    )


class ModelCall(Base):
    __tablename__ = "model_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    trace_id: Mapped[str] = mapped_column(nullable=False)
    provider: Mapped[str | None] = mapped_column()
    model: Mapped[str | None] = mapped_column()
    role: Mapped[str | None] = mapped_column()
    prompt_tokens: Mapped[int | None] = mapped_column()
    output_tokens: Mapped[int | None] = mapped_column()
    ttft_ms: Mapped[int | None] = mapped_column()
    total_latency_ms: Mapped[int | None] = mapped_column()
    status: Mapped[str | None] = mapped_column()
    error_message: Mapped[str | None] = mapped_column(Text)
    cost_cents: Mapped[float | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        Index("idx_model_calls_trace", "trace_id"),
    )


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    trace_id: Mapped[str] = mapped_column(nullable=False)
    tool_name: Mapped[str | None] = mapped_column()
    input_json: Mapped[dict | None] = mapped_column(JSONB)
    output_json: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str | None] = mapped_column()
    latency_ms: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        Index("idx_tool_calls_trace", "trace_id"),
    )


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    schedule_type: Mapped[str] = mapped_column(nullable=False)
    schedule_cron: Mapped[str | None] = mapped_column()
    time_of_day: Mapped[datetime | None] = mapped_column()
    next_fire_at: Mapped[datetime] = mapped_column(nullable=False)
    last_fired_at: Mapped[datetime | None] = mapped_column()
    is_active: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[str] = mapped_column(default="user")
    lease_until: Mapped[datetime | None] = mapped_column()
    lease_owner: Mapped[str | None] = mapped_column()
    retry_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    history: Mapped[list["ReminderHistory"]] = relationship(back_populates="reminder")

    __table_args__ = (
        Index("idx_reminders_next_fire", "next_fire_at", postgresql_where=text("is_active = true")),
        Index("idx_reminders_user", "user_id"),
    )


class ReminderHistory(Base):
    __tablename__ = "reminder_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    reminder_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reminders.id"), nullable=False)
    fired_at: Mapped[datetime] = mapped_column(nullable=False)
    delivered: Mapped[bool] = mapped_column(default=False)
    acknowledged: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    reminder: Mapped[Reminder] = relationship(back_populates="history")


class ReminderDeliveryAttempt(Base):
    __tablename__ = "reminder_delivery_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    reminder_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reminders.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(default=1)
    state: Mapped[str] = mapped_column(default="queued")
    idempotency_key: Mapped[str] = mapped_column(nullable=False)
    due_at: Mapped[datetime] = mapped_column(nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column()
    provider_message_id: Mapped[str | None] = mapped_column()
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column()
    device_received_at: Mapped[datetime | None] = mapped_column()
    played_at: Mapped[datetime | None] = mapped_column()
    acknowledged_at: Mapped[datetime | None] = mapped_column()
    failed_at: Mapped[datetime | None] = mapped_column()
    expired_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_reminder_delivery_attempt_idempotency"),
        Index("idx_reminder_delivery_attempts_reminder", "reminder_id", "created_at"),
        Index("idx_reminder_delivery_attempts_state", "state", "due_at"),
    )


class CareTask(Base):
    """Care-domain task (medication / appointment). Reminder is scheduling projection."""

    __tablename__ = "care_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(nullable=False)
    task_type: Mapped[str] = mapped_column(nullable=False, default="medication")
    status: Mapped[str] = mapped_column(nullable=False, default="pending")
    due_at: Mapped[datetime | None] = mapped_column()
    snooze_until: Mapped[datetime | None] = mapped_column()
    reminder_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reminders.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(default="chat")
    completed_at: Mapped[datetime | None] = mapped_column()
    version: Mapped[int] = mapped_column(default=1)
    idempotency_key: Mapped[str | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        Index("idx_care_tasks_user_status", "user_id", "status"),
        Index("idx_care_tasks_due", "due_at"),
        Index("idx_care_tasks_user_idempotency", "user_id", "idempotency_key", unique=True),
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    key: Mapped[str] = mapped_column(nullable=False)
    operation: Mapped[str] = mapped_column(nullable=False)
    resource_type: Mapped[str] = mapped_column(nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    request_hash: Mapped[str] = mapped_column(nullable=False)
    response_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(default="completed")
    status_code: Mapped[int] = mapped_column(default=200)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "key", "operation", name="uq_idempotency_user_key_operation"),
        Index("idx_idempotency_records_user", "user_id", "created_at"),
        Index("idx_idempotency_records_status", "status", "updated_at"),
    )


class EmergencyContact(Base):
    __tablename__ = "emergency_contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    phone: Mapped[str] = mapped_column(nullable=False)
    relation: Mapped[str | None] = mapped_column()
    priority: Mapped[int] = mapped_column(default=1)
    notify_on_levels: Mapped[list | None] = mapped_column(ARRAY(Text), server_default=text("'{critical,high}'::text[]"))
    webhook_url: Mapped[str | None] = mapped_column()
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (Index("idx_emergency_contacts_user", "user_id"),)


class FamilyBinding(Base):
    __tablename__ = "family_bindings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    family_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    elder_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    permissions: Mapped[list | None] = mapped_column(
        ARRAY(Text),
        server_default=text("'{view_reminders,manage_reminders,view_notifications}'::text[]"),
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (Index("idx_family_bindings_unique", "family_user_id", "elder_user_id", unique=True),)


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("emergency_contacts.id"))
    trace_id: Mapped[str | None] = mapped_column(nullable=True)
    risk_level: Mapped[str] = mapped_column(nullable=False)
    risk_category: Mapped[str | None] = mapped_column()
    summary: Mapped[str | None] = mapped_column(Text)
    webhook_status: Mapped[str | None] = mapped_column()
    safety_decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("safety_decisions.id"))
    outbox_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("notification_outbox.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (Index("idx_notification_log_user", "user_id", "created_at"),)


class SafetyDecision(Base):
    __tablename__ = "safety_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    trace_id: Mapped[str | None] = mapped_column()
    policy_version: Mapped[str] = mapped_column(nullable=False)
    risk_level: Mapped[str] = mapped_column(nullable=False)
    risk_category: Mapped[str] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(nullable=False)
    evidence_ref: Mapped[str | None] = mapped_column()
    evidence_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    confidence: Mapped[float | None] = mapped_column()
    calibration: Mapped[str | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        Index("idx_safety_decisions_user", "user_id", "created_at"),
        Index("idx_safety_decisions_trace", "trace_id"),
    )


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    safety_decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("safety_decisions.id"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("emergency_contacts.id"))
    provider: Mapped[str] = mapped_column(default="sandbox")
    channel: Mapped[str] = mapped_column(default="webhook")
    idempotency_key: Mapped[str] = mapped_column(nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    state: Mapped[str] = mapped_column(default="queued")
    attempt_count: Mapped[int] = mapped_column(default=0)
    attempt_identity: Mapped[str | None] = mapped_column()
    lease_owner: Mapped[str | None] = mapped_column()
    lease_until: Mapped[datetime | None] = mapped_column()
    next_attempt_at: Mapped[datetime | None] = mapped_column()
    last_error: Mapped[str | None] = mapped_column(Text)
    provider_message_id: Mapped[str | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_notification_outbox_idempotency"),
        Index("idx_notification_outbox_state", "state", "next_attempt_at"),
        Index("idx_notification_outbox_lease", "state", "lease_until"),
        Index("idx_notification_outbox_user", "user_id", "created_at"),
    )


class NotificationReceipt(Base):
    __tablename__ = "notification_receipts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    outbox_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notification_outbox.id"), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column()
    receipt_identity: Mapped[str | None] = mapped_column()
    event_type: Mapped[str] = mapped_column(nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("outbox_id", "receipt_identity", name="uq_notification_receipts_identity"),
        Index("idx_notification_receipts_outbox", "outbox_id", "created_at"),
    )


class OperatorCase(Base):
    __tablename__ = "operator_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    safety_decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("safety_decisions.id"))
    notification_outbox_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("notification_outbox.id"))
    status: Mapped[str] = mapped_column(default="open")
    severity: Mapped[str] = mapped_column(default="high")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    summary: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    resolved_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        Index("idx_operator_cases_status", "status", "severity", "created_at"),
        Index("idx_operator_cases_user", "user_id", "created_at"),
    )
