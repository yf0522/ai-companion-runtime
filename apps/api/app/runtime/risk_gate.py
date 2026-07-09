from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import yaml
from nanoid import generate as nanoid

from app.engines.base import AnalyzerInput, RiskResult
from app.runtime.stream_manager import StreamManager

logger = logging.getLogger(__name__)


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
        await _emit_risk_block(risk, stream_mgr, trace_id, start)
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
    except Exception as e:
        logger.warning("Risk gate failed: %s", e)
    return RiskResult()


async def _emit_risk_block(
    risk: RiskResult,
    stream_mgr: StreamManager,
    trace_id: str,
    start: float,
) -> None:
    await stream_mgr.send_risk_alert(risk.level, "")
    safety_msg = _load_safety_message(risk.level)
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


def _load_safety_message(level: str) -> str:
    try:
        path = Path(__file__).parent.parent / "config" / "risk_rules.yaml"
        with open(path) as f:
            rules = yaml.safe_load(f)
        return rules.get("safety_messages", {}).get(level, "") or _default_safety_message()
    except Exception as e:
        logger.error("Failed to load safety messages: %s", e)
        return _default_safety_message()


def _default_safety_message() -> str:
    return "如果你正在经历困难，请拨打心理援助热线：400-161-9995"


def _generate_trace_id(user_id: str) -> str:
    from datetime import datetime

    date_str = datetime.now().strftime("%Y%m%d")
    uid_short = user_id[:8] if len(user_id) > 8 else user_id
    return f"trace_{date_str}_{uid_short}_{nanoid(size=8)}"
