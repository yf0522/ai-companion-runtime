from __future__ import annotations

import asyncio

from app.runtime.agent_harness import AgentHarness
from app.runtime.agent_runtime import RUNTIME_HARNESS
from app.runtime.stream_manager import StreamManager


class HarnessRuntime:
    """Production path — delegates to the existing risk-first AgentHarness."""

    name = RUNTIME_HARNESS

    def __init__(self) -> None:
        self._harness = AgentHarness()

    async def run(
        self,
        user_id: str,
        session_id: str,
        message: str,
        stream_mgr: StreamManager,
        cancel_event: asyncio.Event,
    ) -> dict:
        result = await self._harness.run(
            user_id=user_id,
            session_id=session_id,
            message=message,
            stream_mgr=stream_mgr,
            cancel_event=cancel_event,
        )
        result["agent_runtime"] = self.name
        return result
