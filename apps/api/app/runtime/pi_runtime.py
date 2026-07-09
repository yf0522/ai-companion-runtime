from __future__ import annotations

import asyncio
import logging
import time

from nanoid import generate as nanoid

from app.config.settings import settings
from app.runtime.agent_runtime import RUNTIME_PI_EXPERIMENTAL
from app.runtime.risk_gate import run_risk_gate
from app.runtime.stream_manager import StreamManager

logger = logging.getLogger(__name__)

_PI_DISABLED_MSG = (
    "Pi Agent 运行时（实验）尚未在本环境启用。"
    "请在服务端设置 ENABLE_PI_RUNTIME=1 并部署 Node sidecar 后再试。"
    "当前已回退到安全模式：风险检测仍生效，但不会调用 Pi 循环。"
)


class PiExperimentalRuntime:
    """Experimental Pi agent path — risk gate first, then optional Node sidecar."""

    name = RUNTIME_PI_EXPERIMENTAL

    async def run(
        self,
        user_id: str,
        session_id: str,
        message: str,
        stream_mgr: StreamManager,
        cancel_event: asyncio.Event,
    ) -> dict:
        start = time.monotonic()
        gate = await run_risk_gate(
            user_id=user_id,
            session_id=session_id,
            message=message,
            stream_mgr=stream_mgr,
        )
        if gate.blocked:
            gate.metadata["agent_runtime"] = self.name
            return gate.metadata

        if cancel_event.is_set():
            return {"trace_id": gate.trace_id, "cancelled": True, "agent_runtime": self.name}

        if not settings.enable_pi_runtime:
            return await self._emit_disabled_stub(stream_mgr, gate.trace_id, start)

        # Future: HTTP/subprocess bridge to apps/pi-sidecar (earendil-works/pi).
        return await self._emit_disabled_stub(
            stream_mgr,
            gate.trace_id,
            start,
            detail="Pi sidecar endpoint not configured; set PI_SIDECAR_URL when ready.",
        )

    async def _emit_disabled_stub(
        self,
        stream_mgr: StreamManager,
        trace_id: str,
        start: float,
        detail: str | None = None,
    ) -> dict:
        text = _PI_DISABLED_MSG if detail is None else f"{_PI_DISABLED_MSG}\n\n({detail})"
        ttft_ms = int((time.monotonic() - start) * 1000)
        await stream_mgr.send_first_reply(text, ttft_ms)
        total_latency_ms = int((time.monotonic() - start) * 1000)
        message_id = f"m_{nanoid(size=12)}"
        await stream_mgr.send_final(
            trace_id=trace_id,
            message_id=message_id,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tools_used=[],
            memory_updated=False,
        )
        return {
            "trace_id": trace_id,
            "message_id": message_id,
            "agent_runtime": self.name,
            "pi_experimental": True,
            "error": "pi_experimental_not_enabled",
        }
