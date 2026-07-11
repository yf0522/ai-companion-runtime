"""Memory business adapter — consent, refuse, crisis empty, engine behind Protocol."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any

from app.memory.backend import MemoryEngineBackend, get_memory_backend, mem0_enabled
from app.memory.lifecycle import (
    consent_status_for_environment,
    is_retrievable_memory,
    normalize_uuid,
    select_retrievable_memories,
)
from app.memory.refuse import RefuseDecision, refuse_memory_note

logger = logging.getLogger(__name__)

DEFAULT_RECALL_TIMEOUT_MS = 300

CATEGORY_VALUES = frozenset(
    {"preference", "household_fact", "communication_habit", "persona_style"}
)


@dataclass
class NoteResult:
    status: str  # pending | granted | refused | failed
    memory_id: str | None = None
    refusal_code: str | None = None
    display_text: str = ""
    data: dict[str, Any] | None = None


@dataclass
class RecallResult:
    status: str  # success | empty | timeout | unauthorized
    fragments: list[dict[str, Any]]
    degraded: bool = False
    display_text: str = ""
    data: dict[str, Any] | None = None


def _engine_metric(engine: str, event: str) -> None:
    try:
        from app.observability.metrics import MEMORY_ENGINE_TOTAL

        MEMORY_ENGINE_TOTAL.labels(engine=engine, event=event).inc()
    except Exception:
        pass


class MemoryBusinessAdapter:
    """Own consent / refuse / crisis; delegate extract/rank to MemoryEngineBackend."""

    def __init__(
        self,
        backend: MemoryEngineBackend | None = None,
        *,
        recall_timeout_ms: int = DEFAULT_RECALL_TIMEOUT_MS,
    ) -> None:
        self._backend = backend
        self.recall_timeout_ms = recall_timeout_ms

    @property
    def backend(self) -> MemoryEngineBackend:
        if self._backend is None:
            self._backend = get_memory_backend()
        return self._backend

    async def note(
        self,
        *,
        user_id: str,
        summary: str,
        category: str = "preference",
        explicit_user_request: bool = True,
        session_id: str | None = None,
        trace_id: str | None = None,
        source_actor: str = "elder",
        risk_blocked: bool = False,
        risk_level: str | None = None,
    ) -> NoteResult:
        if risk_blocked or (risk_level or "").lower() in {"high", "critical"}:
            return NoteResult(
                status="refused",
                refusal_code="crisis_skip",
                display_text="当前处于风险保护状态，暂不写入长期记忆。",
                data={"reason": "crisis_skip"},
            )
        if not explicit_user_request:
            return NoteResult(
                status="refused",
                refusal_code="not_explicit",
                display_text="需要您明确说「以后记得…」我才会记下偏好。",
                data={"reason": "not_explicit"},
            )
        text = (summary or "").strip()
        if not text:
            return NoteResult(
                status="failed",
                display_text="没有可记住的内容",
                data={"reason": "empty_summary"},
            )
        decision: RefuseDecision = refuse_memory_note(text)
        if decision.refused:
            return NoteResult(
                status="refused",
                refusal_code=decision.code,
                display_text=decision.display_text,
                data={"reason": decision.code},
            )

        cat = category if category in CATEGORY_VALUES else "preference"
        app_env = (
            os.environ.get("APP_ENV") or os.environ.get("ENV") or "development"
        ).strip()
        consent_status = consent_status_for_environment(app_env)

        # Always persist via lifecycle SoT (consent row). Prefer lifecycle backend for write.
        from app.memory.lifecycle_backend import LifecycleMemoryBackend

        lifecycle = LifecycleMemoryBackend()
        try:
            memory_id = await lifecycle.add(
                user_id=user_id,
                content=text[:500],
                metadata={
                    "category": cat,
                    "source": "tool_note",
                    "source_trace_id": trace_id,
                    "source_actor": source_actor,
                    "session_id": session_id,
                    "consent_status": consent_status,
                    "importance_score": 0.85,
                },
                infer=False,
            )
        except Exception as e:
            logger.error("memory note lifecycle write failed: %s", e, exc_info=True)
            return NoteResult(
                status="failed",
                display_text="记下偏好时出错了，请稍后再试。",
                data={"reason": "store_failed", "error": str(e)},
            )

        # mem0 mirror (engine path) — never replaces consent SoT.
        engine_id: str | None = None
        engine_name = self.backend.name
        if mem0_enabled() and not isinstance(self.backend, LifecycleMemoryBackend):
            try:
                engine_id = await self.backend.add(
                    user_id=user_id,
                    content=text[:500],
                    metadata={
                        "category": cat,
                        "consent_status": consent_status,
                        "lifecycle_id": memory_id,
                        "source": "tool_note",
                    },
                    infer=False,
                )
                _engine_metric(engine_name, "note_mirror_ok")
            except Exception as e:
                logger.warning("mem0 mirror add failed (lifecycle kept): %s", e)
                _engine_metric(engine_name, "note_mirror_fail")

        if consent_status == "pending":
            display = (
                f"我先记下了「{text[:40]}」，等您确认后才会长期记住，"
                "现在还不会用来自动续聊。"
            )
        else:
            display = f"好的，我记住了：{text[:60]}"

        return NoteResult(
            status=consent_status if consent_status in {"pending", "granted"} else "pending",
            memory_id=memory_id,
            display_text=display,
            data={
                "memory_id": memory_id,
                "consent_status": consent_status,
                "category": cat,
                "engine": engine_name,
                "engine_id": engine_id,
            },
        )

    async def recall(
        self,
        *,
        user_id: str,
        query_intent: str = "",
        time_from: str | None = None,
        time_to: str | None = None,
        limit: int = 5,
        risk_blocked: bool = False,
        risk_level: str | None = None,
    ) -> RecallResult:
        engine_name = self.backend.name
        if risk_blocked or (risk_level or "").lower() in {"high", "critical"}:
            return RecallResult(
                status="empty",
                fragments=[],
                degraded=True,
                display_text="",
                data={"reason": "crisis_skip", "engine": engine_name},
            )
        uid = normalize_uuid(user_id)
        if uid is None:
            return RecallResult(
                status="unauthorized",
                fragments=[],
                display_text="",
                data={"reason": "missing_user", "engine": engine_name},
            )

        timeout_s = max(0.05, self.recall_timeout_ms / 1000.0)
        try:
            fragments, meta = await asyncio.wait_for(
                self._recall_inner(
                    user_id=user_id,
                    uid=uid,
                    query_intent=query_intent,
                    time_from=time_from,
                    time_to=time_to,
                    limit=max(1, min(limit, 10)),
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            _engine_metric(engine_name, "timeout")
            return RecallResult(
                status="timeout",
                fragments=[],
                degraded=True,
                display_text="",
                data={
                    "reason": "timeout",
                    "timeout_ms": self.recall_timeout_ms,
                    "engine": engine_name,
                },
            )
        except Exception as e:
            logger.warning("memory recall failed: %s", e)
            _engine_metric(engine_name, "error")
            return RecallResult(
                status="empty",
                fragments=[],
                degraded=True,
                display_text="",
                data={"reason": "error", "error": str(e), "engine": engine_name},
            )

        if not fragments:
            reason = str(meta.get("reason") or "no_granted_memories")
            degraded = bool(meta.get("degraded") or meta.get("no_dump"))
            return RecallResult(
                status="empty",
                fragments=[],
                degraded=degraded,
                display_text="暂时没有已授权的长期记忆可回忆。",
                data={
                    "reason": reason,
                    "engine": engine_name,
                    "no_dump": bool(meta.get("no_dump")),
                },
            )
        lines = [f"- {f['content']}" for f in fragments[:5]]
        return RecallResult(
            status="success",
            fragments=fragments,
            display_text="我记得这些：\n" + "\n".join(lines),
            data={
                "count": len(fragments),
                "engine": engine_name,
            },
        )

    async def _recall_inner(
        self,
        *,
        user_id: str,
        uid: uuid.UUID,
        query_intent: str,
        time_from: str | None,
        time_to: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        filters: dict[str, Any] = {}
        if time_from:
            filters["time_from"] = time_from
        if time_to:
            filters["time_to"] = time_to

        engine_name = self.backend.name
        meta: dict[str, Any] = {"engine": engine_name}

        # Prefer engine search; always re-gate via lifecycle consent.
        engine_hits = await self.backend.search(
            user_id=user_id,
            query=query_intent or "preference household communication",
            limit=limit,
            metadata_filters=filters or None,
        )
        meta["engine_hits"] = len(engine_hits)

        # Build granted id set from lifecycle (authoritative).
        from app.db.session import async_session

        granted: list[dict[str, Any]] = []
        async with async_session() as db:
            for purpose in (
                "care_continuity",
                "preference",
                "household_fact",
                "communication_habit",
                "persona_style",
            ):
                granted.extend(
                    await select_retrievable_memories(
                        db, user_id=uid, purpose=purpose, limit=20
                    )
                )
        granted_by_id = {str(g["id"]): g for g in granted if g.get("id")}
        granted_contents = {str(g.get("content") or "") for g in granted}
        meta["granted_count"] = len(granted)

        fragments: list[dict[str, Any]] = []
        seen: set[str] = set()
        for hit in engine_hits:
            mid = str(hit.get("id") or "")
            content = str(hit.get("content") or "")
            hit_meta = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
            lifecycle_id = str(hit_meta.get("lifecycle_id") or "")
            # Match by lifecycle_id (mem0 closed loop), then engine id, else content.
            row = None
            if lifecycle_id and lifecycle_id in granted_by_id:
                row = granted_by_id[lifecycle_id]
            elif mid and mid in granted_by_id:
                row = granted_by_id[mid]
            elif content and content in granted_contents:
                row = next((g for g in granted if g.get("content") == content), None)
            if row is None:
                # Lifecycle backend already returns only granted — accept those.
                if engine_name == "lifecycle" and mid in granted_by_id:
                    row = granted_by_id[mid]
                elif engine_name == "lifecycle" and is_retrievable_memory(
                    hit.get("metadata") or hit
                ):
                    row = hit_meta if hit_meta else None
                    if row is None and hit.get("consent_status") == "granted":
                        row = {
                            "id": mid,
                            "content": content,
                            "purpose": hit.get("category"),
                            "sensitivity": hit.get("sensitivity"),
                            "created_at": hit.get("created_at"),
                        }
            if row is None:
                continue
            key = str(row.get("id") or content)
            if key in seen:
                continue
            seen.add(key)
            fragments.append(
                {
                    "id": str(row.get("id") or mid),
                    "content": row.get("content") or content,
                    "category": row.get("purpose") or hit.get("category"),
                    "sensitivity": row.get("sensitivity") or hit.get("sensitivity"),
                    "created_at": row.get("created_at") or hit.get("created_at"),
                }
            )
            if len(fragments) >= limit:
                break

        # If engine returned nothing usable:
        # - lifecycle backend: fall back to granted dump / importance top-N (legacy)
        # - mem0 (A3): empty/timeout/empty-hits → empty only — NEVER dump granted lifecycle
        if not fragments and granted and engine_name == "lifecycle":
            from app.memory.lifecycle_backend import _filter_query_intent, _filter_time_window

            rows = list(granted_by_id.values())
            rows = _filter_time_window(
                rows,
                _parse_optional_dt(time_from),
                _parse_optional_dt(time_to),
            )
            rows = _filter_query_intent(rows, query_intent)
            for row in rows[:limit]:
                fragments.append(
                    {
                        "id": str(row["id"]),
                        "content": row["content"],
                        "category": row.get("purpose") or row.get("type"),
                        "sensitivity": row.get("sensitivity"),
                        "created_at": row.get("created_at"),
                    }
                )
        elif not fragments and granted and engine_name != "lifecycle":
            logger.info(
                "mem0/engine empty search — skipping lifecycle dump (backend=%s, "
                "granted=%s, engine_hits=%s)",
                engine_name,
                len(granted),
                len(engine_hits),
            )
            meta["no_dump"] = True
            meta["degraded"] = True
            meta["reason"] = "mem0_empty_no_dump"
            _engine_metric(engine_name, "no_dump")
            _engine_metric(engine_name, "search_empty")
        elif not fragments:
            meta["reason"] = "no_granted_memories"
            _engine_metric(engine_name, "search_empty")
        else:
            _engine_metric(engine_name, "search_hit")

        return fragments, meta


def _parse_optional_dt(value: str | None):
    from datetime import datetime

    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


_ADAPTER: MemoryBusinessAdapter | None = None


def get_memory_adapter() -> MemoryBusinessAdapter:
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = MemoryBusinessAdapter()
    return _ADAPTER
