from __future__ import annotations

import uuid
from datetime import datetime

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None
from sqlalchemy import ForeignKey, Index, Text, text
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
    risk_level: Mapped[str] = mapped_column(nullable=False)
    risk_category: Mapped[str | None] = mapped_column()
    summary: Mapped[str | None] = mapped_column(Text)
    webhook_status: Mapped[str | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (Index("idx_notification_log_user", "user_id", "created_at"),)
