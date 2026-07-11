"""Lifecycle-backed memory engine — Postgres L3 via consent-aware lifecycle helpers."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from app.memory.lifecycle import (
    consent_status_for_environment,
    normalize_uuid,
    select_retrievable_memories,
    store_memory,
)

logger = logging.getLogger(__name__)

CATEGORY_TO_PURPOSE = {
    "preference": "preference",
    "household_fact": "household_fact",
    "communication_habit": "communication_habit",
    "persona_style": "persona_style",
    "care_continuity": "care_continuity",
}

CATEGORY_TO_MEMORY_TYPE = {
    "preference": "preference",
    "household_fact": "fact",
    "communication_habit": "habit",
    "persona_style": "preference",
    "care_continuity": "fact",
}


class LifecycleMemoryBackend:
    """Business-store engine: writes/reads our memories table (consent SoT)."""

    name = "lifecycle"

    async def add(
        self,
        *,
        user_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        infer: bool = False,
    ) -> str | None:
        _ = infer  # rule extract stays in Celery; tool notes are explicit
        meta = metadata or {}
        uid = normalize_uuid(user_id)
        if uid is None:
            return None
        category = str(meta.get("category") or "preference")
        purpose = CATEGORY_TO_PURPOSE.get(category, "care_continuity")
        memory_type = CATEGORY_TO_MEMORY_TYPE.get(category, "fact")
        app_env = (
            os.environ.get("APP_ENV") or os.environ.get("ENV") or "development"
        ).strip()
        consent_status = str(
            meta.get("consent_status") or consent_status_for_environment(app_env)
        )
        session_id = normalize_uuid(meta.get("session_id"))
        from app.db.session import async_session

        async with async_session() as db:
            memory_id = await store_memory(
                db,
                user_id=uid,
                content=content,
                importance_score=float(meta.get("importance_score", 0.85)),
                session_id=session_id,
                source=str(meta.get("source") or "tool_note"),
                source_trace_id=meta.get("source_trace_id"),
                source_actor=str(meta.get("source_actor") or "elder"),
                purpose=purpose,
                retention_days=int(meta.get("retention_days", 365)),
                consent_status=consent_status,
                memory_type=memory_type,
            )
            await db.commit()
            return str(memory_id)

    async def search(
        self,
        *,
        user_id: str,
        query: str,
        limit: int = 5,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        uid = normalize_uuid(user_id)
        if uid is None:
            return []
        filters = metadata_filters or {}
        purpose = filters.get("purpose")
        time_from = _parse_dt(filters.get("time_from"))
        time_to = _parse_dt(filters.get("time_to"))
        from app.db.session import async_session

        async with async_session() as db:
            # Over-fetch then keyword/time filter so consent gate stays in SQL.
            rows = await select_retrievable_memories(
                db,
                user_id=uid,
                purpose=str(purpose) if purpose else "care_continuity",
                limit=max(limit * 3, 15),
            )
            # Also pull preference / household categories when purpose not pinned.
            if not purpose:
                for extra_purpose in (
                    "preference",
                    "household_fact",
                    "communication_habit",
                    "persona_style",
                ):
                    more = await select_retrievable_memories(
                        db, user_id=uid, purpose=extra_purpose, limit=limit
                    )
                    rows.extend(more)

        fragments = _dedupe_by_id(rows)
        fragments = _filter_time_window(fragments, time_from, time_to)
        fragments = _filter_query_intent(fragments, query)
        out: list[dict[str, Any]] = []
        for row in fragments[:limit]:
            out.append(
                {
                    "id": row["id"],
                    "content": row["content"],
                    "score": row.get("importance", 0.0),
                    "category": row.get("purpose") or row.get("type"),
                    "sensitivity": row.get("sensitivity"),
                    "created_at": row.get("created_at"),
                    "consent_status": row.get("consent_status"),
                    "metadata": row,
                }
            )
        return out


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _dedupe_by_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        mid = str(row.get("id") or "")
        if mid and mid in seen:
            continue
        if mid:
            seen.add(mid)
        out.append(row)
    return out


def _filter_time_window(
    rows: list[dict[str, Any]],
    time_from: datetime | None,
    time_to: datetime | None,
) -> list[dict[str, Any]]:
    if time_from is None and time_to is None:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        created = _parse_dt(row.get("created_at"))
        if created is None:
            continue
        if time_from is not None and created < time_from:
            continue
        if time_to is not None and created > time_to:
            continue
        out.append(row)
    return out


def _filter_query_intent(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    if not q or q in {"*", "all", "全部", "记得什么"}:
        return rows
    tokens = [t for t in re_split_tokens(q) if len(t) >= 2]
    if not tokens:
        return rows
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        content = str(row.get("content") or "").lower()
        hits = sum(1 for t in tokens if t in content)
        if hits:
            scored.append((hits, row))
    if not scored:
        # No keyword hit — return importance-ordered rows (empty-on-miss is too harsh for elders).
        return rows
    scored.sort(key=lambda x: (-x[0], -float(x[1].get("importance") or 0)))
    return [r for _, r in scored]


def re_split_tokens(text: str) -> list[str]:
    import re

    return [t for t in re.split(r"[\s,，。、；;！!？?]+", text) if t]
