from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml
from nanoid import generate as nanoid

from app.engines.base import AnalyzerInput, RiskResult
from app.runtime.stream_manager import StreamManager

logger = logging.getLogger(__name__)
_BLOCKED_AUDIT_TIMEOUT_S = 0.25


def _load_safety_messages() -> dict[str, str]:
    """Load safety copy once so risk blocking never performs request-time I/O."""
    try:
        path = Path(__file__).parent.parent / "config" / "risk_rules.yaml"
        with open(path, encoding="utf-8") as config_file:
            rules = yaml.safe_load(config_file) or {}
        configured = rules.get("safety_messages", {}) or {}
        return {str(key): str(value) for key, value in configured.items() if value}
    except Exception as exc:
        logger.error("Failed to load safety messages: %s", exc)
        return {}


_SAFETY_MESSAGES = _load_safety_messages()


def _stable_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, value))


@dataclass
class RiskGateOutcome:
    blocked: bool
    risk: RiskResult
    trace_id: str
    metadata: dict


async def run_risk_gate(
    *,
    user_id: str,
    session_id: str,
    message: str,
    stream_mgr: StreamManager,
    trace_id: str | None = None,
    timeout_ms: int = 100,
) -> RiskGateOutcome:
    """Shared risk pre-check before any agent runtime delegates to a model path."""
    trace_id = trace_id or _generate_trace_id(user_id)
    await stream_mgr.send_trace(trace_id)
    start = time.monotonic()

    risk = await _analyze_risk(user_id, session_id, message, trace_id, timeout_ms)

    if risk.level in ("critical", "high"):
        block_metadata = await _emit_risk_block(
            risk,
            stream_mgr,
            trace_id,
            start,
            user_id=user_id,
            session_id=session_id,
            user_message=message,
        )
        return RiskGateOutcome(
            blocked=True,
            risk=risk,
            trace_id=trace_id,
            metadata={
                "trace_id": trace_id,
                "blocked_by_risk": True,
                "agent_runtime": "risk_gate",
                **block_metadata,
            },
        )

    if risk.level == "medium":
        await _persist_nonblocking_decision(user_id, risk, trace_id)
        await stream_mgr.send_risk_alert(risk.level, "")

    return RiskGateOutcome(
        blocked=False,
        risk=risk,
        trace_id=trace_id,
        metadata={"trace_id": trace_id, "blocked_by_risk": False},
    )


async def _analyze_risk(
    user_id: str,
    session_id: str,
    message: str,
    trace_id: str,
    timeout_ms: int,
) -> RiskResult:
    try:
        from app.engines.risk_engine import RiskEngine

        engine = RiskEngine()
        payload = AnalyzerInput(
            user_id=user_id,
            session_id=session_id,
            message=message,
            trace_id=trace_id,
        )
        return await asyncio.wait_for(engine.analyze(payload), timeout=timeout_ms / 1000.0)
    except asyncio.TimeoutError:
        logger.warning("Risk gate timed out (%sms)", timeout_ms)
    except Exception as exc:
        logger.warning("Risk gate failed: %s", exc)
    return RiskResult(
        level="critical",
        category="safety_unavailable",
        confidence=1.0,
        triggered_rules=["risk_engine_unavailable"],
    )


async def _emit_risk_block(
    risk: RiskResult,
    stream_mgr: StreamManager,
    trace_id: str,
    start: float,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    user_message: str | None = None,
) -> dict:
    if user_id:
        # Required durable safety work: do not cancel the DB/outbox transaction
        # with the best-effort observability timeout used below.
        notify_status = await _dispatch_family_notify(user_id, risk, trace_id)
    else:
        notify_status = {"status": "failed", "error": "missing_user"}
    safety_msg = build_safety_response(
        load_safety_message(risk.level, risk.category),
        notify_status,
    )
    # Level-only alert: safety copy goes once via first_reply (avoid bubble dup).
    await stream_mgr.send_risk_alert(risk.level, "")
    ttft_ms = int((time.monotonic() - start) * 1000)
    await stream_mgr.send_first_reply(safety_msg, ttft_ms)
    total_latency_ms = int((time.monotonic() - start) * 1000)
    await stream_mgr.send_final(
        trace_id=trace_id,
        message_id=f"m_{nanoid(size=12)}",
        ttft_ms=ttft_ms,
        total_latency_ms=total_latency_ms,
        tools_used=[],
        memory_updated=False,
    )
    audit_metadata = {"response_text": safety_msg, "audit_persisted": False}
    if user_id and session_id and user_message is not None:
        try:
            await asyncio.wait_for(
                _persist_blocked_turn_evidence(
                    user_id=user_id,
                    session_id=session_id,
                    trace_id=trace_id,
                    user_message=user_message,
                    assistant_message=safety_msg,
                    risk=risk,
                    notify_status=notify_status,
                    total_latency_ms=total_latency_ms,
                ),
                timeout=_BLOCKED_AUDIT_TIMEOUT_S,
            )
            audit_metadata["audit_persisted"] = True
        except Exception as exc:
            # Emergency guidance and terminal stream events have already been
            # emitted. Surface audit degradation without withholding safety.
            logger.error("Blocked-turn audit persistence failed trace=%s: %s", trace_id, exc)
            audit_metadata["audit_error"] = type(exc).__name__
    return audit_metadata


async def _persist_blocked_turn_evidence(
    *,
    user_id: str,
    session_id: str,
    trace_id: str,
    user_message: str,
    assistant_message: str,
    risk: RiskResult,
    notify_status: dict,
    total_latency_ms: int,
) -> None:
    """Persist reconstructable blocked-turn evidence without raw trace text."""
    from app.observability.message_evidence import persist_turn_messages
    from app.observability.trace_service import TraceService

    persisted = await persist_turn_messages(
        session_id=session_id,
        user_id=user_id,
        trace_id=trace_id,
        user_content=user_message,
        assistant_content=assistant_message,
    )
    trace = TraceService()
    common = {
        "risk_level": risk.level,
        "risk_category": risk.category or "unknown",
        "triggered_rule_types": _redacted_rule_types(risk.triggered_rules),
    }
    await trace.add_event(
        trace_id=trace_id,
        step_name="incoming_turn",
        step_index=0,
        user_id=user_id,
        session_id=session_id,
        input_json={**common, "content_redacted": True, "content_chars": len(user_message)},
        required=True,
    )
    await trace.add_event(
        trace_id=trace_id,
        step_name="final_outcome",
        step_index=99,
        user_id=user_id,
        session_id=session_id,
        output_json={
            **common,
            "blocked_by_risk": True,
            "content_redacted": True,
            "content_chars": len(assistant_message),
            "assistant_message_id": persisted.assistant_message_id,
            "notification_state": _bounded_notification_state(notify_status),
        },
        latency_ms=total_latency_ms,
        required=True,
    )


def _bounded_notification_state(status: dict | None) -> str:
    status = status or {}
    webhook_status = str(status.get("webhook_status") or "")
    if webhook_status in {"delivered", "read", "acknowledged", "no_contact"}:
        return webhook_status
    if status.get("outbox_ids"):
        return "queued"
    return "failed"


def _redacted_rule_types(rules: list[str] | None) -> list[str]:
    """Keep bounded rule classes while dropping matched user fragments."""
    return [str(rule).split(":", 1)[0][:40] for rule in (rules or [])[:10]]


def load_safety_message(level: str, category: str | None = None) -> str:
    """Return CN-safe copy, preferring category-specific crisis guidance."""
    if category:
        for key in (f"{level}_{category}", category):
            if message := _SAFETY_MESSAGES.get(key):
                return message
    if message := _SAFETY_MESSAGES.get(level):
        return message
    return _default_safety_message()


def _default_safety_message() -> str:
    return (
        "如果你正在经历困难，请拨打全国统一心理援助热线 12356，"
        "或希望24小时热线 400-161-9995"
    )


def build_safety_response(base_message: str, notify_status: dict | None) -> str:
    """Append truthful family-contact state without claiming unconfirmed delivery."""
    status = notify_status or {}
    webhook_status = str(status.get("webhook_status") or "")
    outbox_ids = status.get("outbox_ids") or []
    if webhook_status in {"delivered", "read", "acknowledged"}:
        notice = "您的家人已经收到通知。"
    elif outbox_ids:
        notice = "我已尝试联系您的家人，消息正在发送，送达状态还在确认。"
    elif webhook_status == "no_contact":
        notice = "目前没有可通知的已验证家属联系人，请立即联系身边可信任的人。"
    else:
        notice = "我暂时无法联系到您的家人，请立即联系身边可信任的人。"
    return f"{base_message.rstrip()} {notice}"


async def _dispatch_family_notify(user_id: str, risk: RiskResult, trace_id: str) -> dict:
    """Persist the shared safety/outbox pipeline before any provider delivery."""
    try:
        from app.config.settings import settings
        from app.workers.notification_outbox_worker import (
            create_safety_notification_pipeline,
            deliver_notification_outbox,
        )
        summary = _family_summary(risk)
        result = await create_safety_notification_pipeline(
            user_id=_stable_uuid(user_id),
            risk_level=risk.level,
            risk_category=risk.category or "unknown",
            summary=summary,
            trace_id=trace_id,
        )
        if settings.enable_celery_tasks and result.get("outbox_ids"):
            deliver_notification_outbox.delay()
            result["delivery_queued"] = True
        return result
    except Exception as exc:
        logger.warning("Risk gate family notify failed: %s", exc)
        return {"status": "failed", "outbox_ids": [], "error": str(exc)}


async def _persist_nonblocking_decision(user_id: str, risk: RiskResult, trace_id: str) -> dict:
    try:
        from app.workers.notification_outbox_worker import persist_nonblocking_safety_decision

        return await persist_nonblocking_safety_decision(
            user_id=_stable_uuid(user_id),
            risk_level=risk.level,
            risk_category=risk.category or "unknown",
            trace_id=trace_id,
            evidence_json={"triggered_rules": list(risk.triggered_rules or [])},
            confidence=risk.confidence,
        )
    except Exception as exc:
        logger.warning("Non-blocking safety decision persistence failed: %s", exc)
        return {"status": "failed", "outbox_ids": [], "error": str(exc)}


def _family_summary(risk: RiskResult) -> str:
    if risk.category == "emotional_crisis":
        return "情绪危机：检测到自杀意念相关表述，请尽快联系老人并确认安全。"
    if risk.category == "scam_alert":
        return "疑似反诈：检测到高风险表述，建议家属尽快确认。"
    if risk.category == "health_emergency":
        return "高危健康信号：建议立即联系家属并协助就医。"
    if risk.level in {"high", "critical"}:
        return "检测到高风险行为，建议先与家属确认后再处理后续动作。"
    return "检测到风险内容，请关注并适时回访。"


def _generate_trace_id(user_id: str) -> str:
    from datetime import datetime

    date_str = datetime.now().strftime("%Y%m%d")
    uid_short = user_id[:8] if len(user_id) > 8 else user_id
    return f"trace_{date_str}_{uid_short}_{nanoid(size=8)}"
