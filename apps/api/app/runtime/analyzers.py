"""Shared analyzer orchestration for the Pi production runtime.

Parity contract (PRD A1/A8):
- intent / emotion / personality: sync on the agent path with timeout budgets
- reflection: async Celery enqueue only (not a sync analyzer step)
- 超时即跳过: analyzer failures/timeouts yield documented defaults
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.engines.base import (
    AnalyzerInput,
    EmotionResult,
    IntentResult,
    MemorySnapshot,
    PersonalityConfig,
    RiskResult,
)
from app.observability.trace_service import TraceService
from app.runtime.stream_manager import StreamManager

logger = logging.getLogger(__name__)
_trace_svc = TraceService()

# TTFT / fast-reply budget (ms) — gate C / U7 parity target.
FAST_REPLY_BUDGET_MS = 300
ANALYZER_DEFAULT_TIMEOUT_MS = 100
MEMORY_RECALL_DEFAULT_TIMEOUT_MS = 300

_engine_cache: dict[str, object] = {}
_runtime_config: dict | None = None


def _load_timeout_config() -> dict:
    global _runtime_config
    if _runtime_config is not None:
        return _runtime_config
    path = Path(__file__).parent.parent / "config" / "runtime.yaml"
    try:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
            _runtime_config = raw.get("runtime", {}) or {}
    except Exception as exc:
        logger.warning("Failed to load runtime.yaml timeouts: %s — using defaults", exc)
        _runtime_config = {}
    return _runtime_config


def analyzer_timeout_ms(key: str = "analyzer") -> int:
    cfg = _load_timeout_config()
    defaults = {
        "analyzer": ANALYZER_DEFAULT_TIMEOUT_MS,
        "memory_recall": MEMORY_RECALL_DEFAULT_TIMEOUT_MS,
        "fast_reply": FAST_REPLY_BUDGET_MS,
    }
    return int(cfg.get("timeouts", {}).get(key, defaults.get(key, ANALYZER_DEFAULT_TIMEOUT_MS)))


def stable_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, value))


def get_cached_engine(name: str):
    if name in _engine_cache:
        return _engine_cache[name]
    try:
        if name == "intent":
            from app.engines.intent_engine import IntentEngine

            _engine_cache[name] = IntentEngine()
        elif name == "emotion":
            from app.engines.emotion_engine import EmotionEngine

            _engine_cache[name] = EmotionEngine()
        elif name == "risk":
            from app.engines.risk_engine import RiskEngine

            _engine_cache[name] = RiskEngine()
        elif name == "memory":
            from app.engines.memory_engine import MemoryEngine

            _engine_cache[name] = MemoryEngine()
        elif name == "personality":
            from app.engines.personality_engine import PersonalityEngine

            _engine_cache[name] = PersonalityEngine()
    except ImportError:
        return None
    return _engine_cache.get(name)


@dataclass
class AnalyzerBundle:
    intent: IntentResult
    emotion: EmotionResult
    memory: MemorySnapshot
    personality: PersonalityConfig
    latency_ms: int


async def run_intent_emotion_memory(
    analyzer_input: AnalyzerInput,
    *,
    include_memory: bool = True,
) -> tuple[IntentResult, EmotionResult, MemorySnapshot]:
    """Run intent/emotion/(optional memory) with harness-equivalent timeouts."""
    timeout_ms = analyzer_timeout_ms("analyzer")

    async def _safe_analyze(engine_name: str, default: Any) -> Any:
        try:
            engine = get_cached_engine(engine_name)
            if engine:
                return await asyncio.wait_for(
                    engine.analyze(analyzer_input),
                    timeout=timeout_ms / 1000,
                )
        except asyncio.TimeoutError:
            logger.warning("%s timed out (%sms)", engine_name, timeout_ms)
        except Exception as exc:
            logger.warning("%s failed: %s", engine_name, exc)
        return default

    async def _safe_memory() -> MemorySnapshot:
        if not include_memory:
            return MemorySnapshot()
        mem_timeout = analyzer_timeout_ms("memory_recall")
        try:
            engine = get_cached_engine("memory")
            if engine:
                return await asyncio.wait_for(
                    engine.analyze(analyzer_input),
                    timeout=mem_timeout / 1000,
                )
        except asyncio.TimeoutError:
            logger.warning("Memory recall timed out (%sms)", mem_timeout)
        except Exception as exc:
            logger.warning("Memory recall failed: %s", exc)
        return MemorySnapshot()

    intent, emotion, memory = await asyncio.gather(
        _safe_analyze("intent", IntentResult(primary_intent="chitchat", confidence=0.5)),
        _safe_analyze("emotion", EmotionResult()),
        _safe_memory(),
    )
    return intent, emotion, memory


async def get_personality(
    emotion: EmotionResult,
    intent: IntentResult | None = None,
) -> PersonalityConfig:
    engine = get_cached_engine("personality")
    if engine is None:
        try:
            from app.engines.personality_engine import PersonalityEngine

            _engine_cache["personality"] = PersonalityEngine()
            engine = _engine_cache["personality"]
        except ImportError:
            return PersonalityConfig()
    return await engine.adapt(emotion=emotion, intent=intent)


async def run_analyzer_chain(
    *,
    user_id: str,
    session_id: str,
    message: str,
    trace_id: str,
    include_memory: bool = True,
) -> AnalyzerBundle:
    """Full sync analyzer + personality chain for Pi path (risk already gated)."""
    start = time.monotonic()
    analyzer_input = AnalyzerInput(
        user_id=user_id,
        session_id=session_id,
        message=message,
        trace_id=trace_id,
    )
    intent, emotion, memory = await run_intent_emotion_memory(
        analyzer_input, include_memory=include_memory
    )
    personality = await get_personality(emotion, intent)
    return AnalyzerBundle(
        intent=intent,
        emotion=emotion,
        memory=memory,
        personality=personality,
        latency_ms=int((time.monotonic() - start) * 1000),
    )


async def record_analyzer_events(
    *,
    trace_id: str,
    user_id: str,
    session_id: str,
    intent: IntentResult,
    emotion: EmotionResult,
    personality: PersonalityConfig,
    latency_ms: int,
    risk: RiskResult | None = None,
    memory: MemorySnapshot | None = None,
) -> None:
    """Emit parity trace steps (intent/emotion/personality; optional risk/memory)."""
    db_user = stable_uuid(user_id)
    db_session = stable_uuid(session_id)
    tasks = [
        _trace_svc.add_event(
            trace_id=trace_id,
            step_name="intent_detection",
            step_index=1,
            user_id=db_user,
            session_id=db_session,
            output_json=intent.model_dump(),
            status="success",
            latency_ms=latency_ms,
        ),
        _trace_svc.add_event(
            trace_id=trace_id,
            step_name="emotion_detection",
            step_index=2,
            user_id=db_user,
            session_id=db_session,
            output_json=emotion.model_dump(),
            status="success",
            latency_ms=latency_ms,
        ),
        _trace_svc.add_event(
            trace_id=trace_id,
            step_name="personality_adapt",
            step_index=5,
            user_id=db_user,
            session_id=db_session,
            output_json=personality.model_dump(),
            status="success",
            latency_ms=latency_ms,
        ),
    ]
    if risk is not None:
        tasks.append(
            _trace_svc.add_event(
                trace_id=trace_id,
                step_name="risk_detection",
                step_index=3,
                user_id=db_user,
                session_id=db_session,
                output_json=risk.model_dump(),
                status="success",
                latency_ms=latency_ms,
            )
        )
    if memory is not None:
        tasks.append(
            _trace_svc.add_event(
                trace_id=trace_id,
                step_name="memory_recall",
                step_index=4,
                user_id=db_user,
                session_id=db_session,
                output_json={
                    "working_count": len(memory.working or []),
                    "vector_count": len(memory.vectors or []),
                    "has_summary": bool(memory.summary),
                    "has_profile": bool(memory.profile),
                },
                status="success",
                latency_ms=latency_ms,
            )
        )
    await asyncio.gather(*tasks)


def build_personality_system_prompt(
    personality: PersonalityConfig,
    emotion: EmotionResult,
    intent: IntentResult | None = None,
) -> str:
    """Assemble sidecar system prompt fragments from personality + emotion."""
    parts = [
        f"You are a warm AI companion. Style: {personality.tone}.",
        "Reply in the user's language. Keep answers practical and kind.",
    ]
    if personality.style_rules:
        parts.append("Behavior: " + "；".join(personality.style_rules))
    if emotion.emotion != "neutral":
        parts.append(
            f"User emotion: {emotion.emotion} (intensity {emotion.intensity:.1f}, trend {emotion.trend})."
        )
    if intent and intent.primary_intent:
        parts.append(f"User intent: {intent.primary_intent}.")
    if personality.avoid_phrases:
        parts.append("Avoid: " + "、".join(personality.avoid_phrases))
    if personality.max_length:
        parts.append(f"Reply within {personality.max_length} characters when possible.")
    parts.extend(
        [
            "When the user asks about medication, appointments, or care tasks, use the caretask tool.",
            "For today's care tasks / 今日事项, use caretask action=list (defaults to today's care window).",
            "When the user says 以后记得 / preferences / continuity facts, use the memory tool (note or recall).",
            "For weather, math, or web lookup, use the utility tool (op=weather|calculator|search).",
            "Never store prescription doses or escalation rules in memory — those belong to caretask.",
            "Never claim a tool succeeded if the tool result status is failed or timeout.",
        ]
    )
    return " ".join(parts)


async def fast_reply_race(
    message: str,
    emotion: EmotionResult,
    personality: PersonalityConfig,
    stream_mgr: StreamManager,
    start_time: float,
    cancel_event: asyncio.Event,
    *,
    budget_ms: int | None = None,
    trace_id: str | None = None,
    user_id: str | None = None,
) -> tuple[bool, int | None]:
    """A2a: emit first_reply without waiting on the sidecar tool loop.

    Returns (sent, ttft_ms). Uses fast model when configured; otherwise False.
    """
    timeout_ms = budget_ms if budget_ms is not None else analyzer_timeout_ms("fast_reply")
    try:
        from app.models.router import model_router

        try:
            model = await model_router.get_model("fast")
        except Exception:
            logger.debug("No fast model configured, skipping fast reply")
            return False, None

        fast_prompt = [
            {
                "role": "system",
                "content": (
                    f"你是一个{personality.tone}的 AI Companion。"
                    f"用户当前情绪：{emotion.emotion}(强度{emotion.intensity})。"
                    f"请用一句自然的话回应用户，不超过{personality.max_length or 80}字。"
                ),
            },
            {"role": "user", "content": message},
        ]

        async def get_first_token():
            async for token in model.stream_chat(fast_prompt):
                return token
            return None

        try:
            first_token = await asyncio.wait_for(
                get_first_token(),
                timeout=timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            logger.debug("Fast reply timed out after %sms", timeout_ms)
            return False, None

        if first_token and not cancel_event.is_set():
            ttft_ms = int((time.monotonic() - start_time) * 1000)
            await stream_mgr.send_first_reply(first_token, ttft_ms)
            if trace_id and user_id:
                try:
                    await _trace_svc.add_event(
                        trace_id=trace_id,
                        step_name="first_reply",
                        step_index=6,
                        user_id=stable_uuid(user_id),
                        output_json={
                            "source": "fast_reply_race",
                            "ttft_ms": ttft_ms,
                            "budget_ms": timeout_ms,
                            "within_budget": ttft_ms <= timeout_ms + 50,
                        },
                        status="success",
                        latency_ms=ttft_ms,
                    )
                except Exception as exc:
                    logger.debug("first_reply trace skipped: %s", exc)
            return True, ttft_ms
    except Exception as exc:
        logger.warning("Fast reply race failed: %s", exc)
    return False, None


async def enqueue_post_process(
    *,
    user_id: str,
    session_id: str,
    user_message: str,
    ai_response: str,
) -> dict[str, bool]:
    """Async post-process parity: L0 persist + Celery memory/reflection enqueue.

    Reflection is never a sync analyzer — only `.delay()` when Celery enabled.
    """
    enqueued = {"memory": False, "reflection": False, "summary": False}
    try:
        from app.storage.working_memory import append_message

        await append_message(session_id, "user", user_message)
        if ai_response:
            await append_message(session_id, "assistant", ai_response)
    except Exception as exc:
        logger.warning("Failed to persist conversation to L0: %s", exc)

    from app.config.settings import settings

    if not settings.enable_celery_tasks:
        return enqueued

    try:
        from app.workers.memory_worker import evaluate_importance, update_session_summary

        evaluate_importance.delay(user_id, user_message, session_id)
        enqueued["memory"] = True
        if ai_response:
            update_session_summary.delay(session_id)
            enqueued["summary"] = True
    except Exception as exc:
        logger.debug("Celery memory tasks skipped: %s", exc)

    try:
        from app.workers.reflection_worker import run_reflection

        run_reflection.delay(user_id, session_id)
        enqueued["reflection"] = True
    except Exception as exc:
        logger.debug("Celery reflection enqueue skipped: %s", exc)

    return enqueued
