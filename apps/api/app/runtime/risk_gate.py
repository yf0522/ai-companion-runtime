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
        await _emit_risk_block(risk, stream_mgr, trace_id, start, user_id=user_id)
        return RiskGateOutcome(
            blocked=True,
            risk=risk,
            trace_id=trace_id,
            metadata={"trace_id": trace_id, "blocked_by_risk": True, "agent_runtime": "risk_gate"},
        )

    if risk.level == "medium":
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
) -> None:
    safety_msg = load_safety_message(risk.level, risk.category)
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
    if user_id:
        await _dispatch_family_notify(user_id, risk, trace_id)


def load_safety_message(level: str, category: str | None = None) -> str:
    """Load CN-safe template; prefer category-specific copy for emotional crisis."""
    try:
        path = Path(__file__).parent.parent / "config" / "risk_rules.yaml"
        with open(path) as f:
            rules = yaml.safe_load(f) or {}
        messages = rules.get("safety_messages", {}) or {}
        if category:
            for key in (f"{level}_{category}", category):
                msg = messages.get(key)
                if msg:
                    return str(msg)
        msg = messages.get(level)
        if msg:
            return str(msg)
    except Exception as exc:
        logger.error("Failed to load safety messages: %s", exc)
    return _default_safety_message()


def _default_safety_message() -> str:
    return (
        "如果你正在经历困难，请拨打全国统一心理援助热线 12356，"
        "或希望24小时热线 400-161-9995"
    )


async def _dispatch_family_notify(user_id: str, risk: RiskResult, trace_id: str) -> None:
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
    except Exception as exc:
        logger.warning("Risk gate family notify failed: %s", exc)


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
