from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Column, DateTime, String, and_, insert, select, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Base
import app.db.memory_models  # noqa: F401

MEMORY_POLICY_VERSION = "memory-lifecycle-2026-07-10"
DEFAULT_EXTRACTION_MODEL = "rule_importance"
DEFAULT_EXTRACTION_MODEL_VERSION = "2026-07-10"
DEFAULT_EMBEDDING_MODEL = "text-embedding-v3"
DEFAULT_EMBEDDING_MODEL_VERSION = "dashscope-compatible-2026-07-10"

RETRIEVABLE_CONSENT_STATUSES = {"granted"}
ACTIVE_DELETION_STATE = "active"
CARE_SUMMARY_STATUS_MAP = {
    "done": "completed",
    "completed": "completed",
    "acknowledged": "acknowledged",
    "missed": "missed",
    "failed": "failed",
    "expired": "expired",
    "cancelled": "cancelled",
    "snoozed": "snoozed",
}

SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r"降压药|胰岛素|二甲双胍|吃药|用药|药物|复诊|医生|医院|高血压|糖尿病|心脏病|胸口疼", "health"),
    (r"紧急联系人|儿子|女儿|孙子|孙女|家人|爸爸|妈妈|老公|老婆", "family_contact"),
    (r"地址|住在|小区|门牌|定位|位置", "location"),
    (r"验证码|转账|银行卡|密码|诈骗|骗子", "financial_safety"),
]


def memories_table():
    table = Base.metadata.tables["memories"]
    for column in (
        Column("source", String),
        Column("source_trace_id", String),
        Column("source_actor", String),
        Column("purpose", String),
        Column("sensitivity", String),
        Column("retention_until", DateTime),
        Column("consent_grant_id", UUID(as_uuid=True)),
        Column("consent_status", String),
        Column("extraction_model", String),
        Column("extraction_model_version", String),
        Column("correction_state", String),
        Column("deletion_state", String),
        Column("deleted_at", DateTime),
        Column("embedding_state", String),
        Column("embedding_model", String),
        Column("embedding_model_version", String),
        Column("embedding_deleted_at", DateTime),
    ):
        if column.name not in table.c:
            table.append_column(column)
    return table


def memory_embeddings_table():
    table = Base.metadata.tables["memory_embeddings"]
    for column in (
        Column("model_version", String),
        Column("state", String),
        Column("deleted_at", DateTime),
    ):
        if column.name not in table.c:
            table.append_column(column)
    return table


def normalize_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return uuid.uuid5(uuid.NAMESPACE_DNS, str(value))


def detect_sensitivity(content: str) -> str:
    for pattern, sensitivity in SENSITIVE_PATTERNS:
        if re.search(pattern, content):
            return sensitivity
    return "general"


def retention_deadline(retention_days: int | None, now: datetime | None = None) -> datetime | None:
    if retention_days is None:
        return None
    current = now or datetime.now(UTC)
    return current.replace(tzinfo=None) + timedelta(days=retention_days)


def is_retrievable_memory(row: Any, *, now: datetime | None = None) -> bool:
    current = (now or datetime.now(UTC)).replace(tzinfo=None)
    consent_status = _row_value(row, "consent_status", "legacy_unverified")
    deletion_state = _row_value(row, "deletion_state", "active")
    retention_until = _row_value(row, "retention_until")
    if consent_status not in RETRIEVABLE_CONSENT_STATUSES:
        return False
    if deletion_state != ACTIVE_DELETION_STATE:
        return False
    if retention_until is not None and retention_until < current:
        return False
    return True


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if hasattr(row, key):
        return getattr(row, key)
    if isinstance(row, dict):
        return row.get(key, default)
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping.get(key, default)
    return default


def serialize_memory(row: Any) -> dict[str, Any]:
    return {
        "id": str(_row_value(row, "id")),
        "content": _row_value(row, "content"),
        "type": _row_value(row, "memory_type"),
        "importance": float(_row_value(row, "importance_score", 0.0) or 0.0),
        "purpose": _row_value(row, "purpose"),
        "sensitivity": _row_value(row, "sensitivity"),
        "consent_status": _row_value(row, "consent_status"),
        "retention_until": _iso(_row_value(row, "retention_until")),
        "correction_state": _row_value(row, "correction_state"),
        "deletion_state": _row_value(row, "deletion_state"),
        "embedding_state": _row_value(row, "embedding_state"),
        "source": _row_value(row, "source"),
        "source_trace_id": _row_value(row, "source_trace_id"),
        "created_at": _iso(_row_value(row, "created_at")),
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def consent_status_for_environment(app_env: str) -> str:
    return "pending" if app_env.lower() == "production" else "granted"


async def store_memory(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    content: str,
    importance_score: float,
    session_id: uuid.UUID | None = None,
    source: str = "chat",
    source_trace_id: str | None = None,
    source_actor: str | None = "elder",
    purpose: str = "care_continuity",
    retention_days: int | None = 365,
    consent_grant_id: uuid.UUID | None = None,
    consent_status: str = "pending",
    memory_type: str = "fact",
) -> uuid.UUID:
    table = memories_table()
    result = await db.execute(
        insert(table)
        .values(
            user_id=user_id,
            session_id=session_id,
            content=content[:500],
            memory_type=memory_type,
            importance_score=importance_score,
            source=source,
            source_trace_id=source_trace_id,
            source_actor=source_actor,
            purpose=purpose,
            sensitivity=detect_sensitivity(content),
            retention_until=retention_deadline(retention_days),
            consent_grant_id=consent_grant_id,
            consent_status=consent_status,
            extraction_model=DEFAULT_EXTRACTION_MODEL,
            extraction_model_version=DEFAULT_EXTRACTION_MODEL_VERSION,
            correction_state="original",
            deletion_state="active",
            embedding_state="pending",
        )
        .returning(table.c.id)
    )
    return result.scalar_one()


async def select_retrievable_memories(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    purpose: str = "care_continuity",
    limit: int = 5,
) -> list[dict[str, Any]]:
    table = memories_table()
    now = datetime.now(UTC).replace(tzinfo=None)
    result = await db.execute(
        select(table)
        .where(
            and_(
                table.c.user_id == user_id,
                table.c.purpose == purpose,
                table.c.consent_status == "granted",
                table.c.deletion_state == "active",
                (table.c.retention_until.is_(None) | (table.c.retention_until >= now)),
            )
        )
        .order_by(table.c.importance_score.desc(), table.c.created_at.desc())
        .limit(limit)
    )
    return [serialize_memory(row) for row in result.fetchall()]


async def correct_memory(
    db: AsyncSession,
    *,
    memory_id: uuid.UUID,
    user_id: uuid.UUID,
    corrected_content: str,
    requested_by: uuid.UUID | None = None,
    reason: str | None = None,
) -> bool:
    table = memories_table()
    result = await db.execute(
        select(table.c.content).where(
            and_(table.c.id == memory_id, table.c.user_id == user_id, table.c.deletion_state == "active")
        )
    )
    original = result.scalar_one_or_none()
    if original is None:
        return False
    corrections = Base.metadata.tables["memory_correction_events"]
    await db.execute(
        insert(corrections).values(
            memory_id=memory_id,
            user_id=user_id,
            requested_by=requested_by,
            original_content=original,
            corrected_content=corrected_content[:500],
            reason=reason,
            status="applied",
        )
    )
    await db.execute(
        update(table)
        .where(table.c.id == memory_id)
        .values(
            content=corrected_content[:500],
            correction_state="corrected",
            embedding_state="pending",
            sensitivity=detect_sensitivity(corrected_content),
        )
    )
    return True


async def delete_memory(db: AsyncSession, *, memory_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    table = memories_table()
    embeddings = memory_embeddings_table()
    now = datetime.now(UTC).replace(tzinfo=None)
    result = await db.execute(
        update(table)
        .where(and_(table.c.id == memory_id, table.c.user_id == user_id, table.c.deletion_state == "active"))
        .values(
            deletion_state="deleted",
            deleted_at=now,
            embedding_state="deleted",
            embedding_deleted_at=now,
        )
        .returning(table.c.id)
    )
    deleted_id = result.scalar_one_or_none()
    if deleted_id is None:
        return False
    await db.execute(
        update(embeddings)
        .where(embeddings.c.memory_id == memory_id)
        .values(state="deleted", deleted_at=now, embedding=None)
    )
    return True


def build_privacy_safe_family_summary(care_outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    filtered = [
        {**item, "status": CARE_SUMMARY_STATUS_MAP[item["status"]]}
        for item in care_outcomes
        if item.get("status") in CARE_SUMMARY_STATUS_MAP
    ]
    by_status: dict[str, int] = {}
    for item in filtered:
        status = str(item.get("status"))
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "summary_type": "care_outcomes_only",
        "total_outcomes": len(filtered),
        "by_status": by_status,
        "items": [
            {
                "task_id": str(item.get("id")),
                "task_type": item.get("task_type"),
                "status": item.get("status"),
                "due_at": _iso(item.get("due_at")),
                "completed_at": _iso(item.get("completed_at")),
            }
            for item in filtered
        ],
    }
