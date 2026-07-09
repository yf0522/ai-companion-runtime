from __future__ import annotations

import asyncio
import logging
import time

from app.tools.base import ToolBase, ToolResult
from app.runtime.stream_manager import StreamManager

logger = logging.getLogger(__name__)


class ToolDispatcher:
    def __init__(self, max_tool_calls: int = 3, tool_timeout_ms: int = 3000):
        self._max_tool_calls = max_tool_calls
        self._tool_timeout_ms = tool_timeout_ms
        self._tools: dict[str, ToolBase] = {}
        self._register_defaults()

    def _register_defaults(self):
        from app.tools.weather_tool import WeatherTool
        from app.tools.calculator_tool import CalculatorTool
        try:
            from app.tools.search_tool import SearchTool
            self.register(SearchTool())
        except ImportError:
            pass
        try:
            from app.tools.reminder_tool import ReminderTool
            self.register(ReminderTool())
        except ImportError:
            pass
        self.register(WeatherTool())
        self.register(CalculatorTool())

    def register(self, tool: ToolBase):
        self._tools[tool.name] = tool

    async def dispatch(
        self,
        tool_needs: list[str],
        message: str,
        trace_id: str,
        stream_mgr: StreamManager,
    ) -> list[ToolResult]:
        tasks = []
        for name in tool_needs[: self._max_tool_calls]:
            if name in self._tools:
                tasks.append(self._call_tool(name, message, trace_id, stream_mgr))
            else:
                logger.warning(f"Unknown tool: {name}")

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, ToolResult)]

    async def _record_tool_call(
        self,
        *,
        trace_id: str,
        tool_name: str,
        input_json: dict,
        output_json: dict | None,
        status: str,
        latency_ms: int,
    ) -> None:
        """Best-effort persistence — never break chat on trace DB failure."""
        try:
            from app.observability.trace_service import TraceService

            await TraceService().record_tool_call(
                trace_id=trace_id,
                tool_name=tool_name,
                input_json=input_json,
                output_json=output_json,
                status=status,
                latency_ms=latency_ms,
            )
        except Exception as e:
            logger.error(f"Failed to persist tool call for {tool_name}: {e}")

    async def _call_tool(
        self,
        name: str,
        message: str,
        trace_id: str,
        stream_mgr: StreamManager,
    ) -> ToolResult:
        tool = self._tools[name]
        await stream_mgr.send_tool_status(name, "calling")
        start = time.monotonic()
        input_json = {"query": message}

        try:
            result = await asyncio.wait_for(
                tool.execute({"query": message}),
                timeout=self._tool_timeout_ms / 1000,
            )
            latency = int((time.monotonic() - start) * 1000)
            result.latency_ms = latency

            # Check for WS actions embedded in tool result data.
            # Tools can request the dispatcher send structured messages to the
            # ESP32 without knowing about WebSocket themselves.
            if result.data and result.data.get("action"):
                action = result.data["action"]
                if action == "reminder_create":
                    ws_data = {
                        k: v
                        for k, v in result.data.items()
                        if k not in ("action", "display_time")
                    }
                    await stream_mgr.send_reminder_create(ws_data)

            if result.status == "success":
                await stream_mgr.send_tool_status(name, "success")
                await stream_mgr.send_tool_result(name, result.display_text)
            else:
                await stream_mgr.send_tool_status(name, "failed")

            await self._record_tool_call(
                trace_id=trace_id,
                tool_name=name,
                input_json=input_json,
                output_json={
                    "status": result.status,
                    "display_text": result.display_text,
                    "data": result.data,
                },
                status=result.status,
                latency_ms=latency,
            )
            return result

        except asyncio.TimeoutError:
            latency = int((time.monotonic() - start) * 1000)
            await stream_mgr.send_tool_status(name, "failed")
            await self._record_tool_call(
                trace_id=trace_id,
                tool_name=name,
                input_json=input_json,
                output_json={"status": "timeout", "display_text": "", "data": None},
                status="timeout",
                latency_ms=latency,
            )
            return ToolResult(
                tool_name=name, status="timeout", display_text="", latency_ms=latency
            )

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            logger.error(f"Tool {name} error: {e}")
            await stream_mgr.send_tool_status(name, "failed")
            await self._record_tool_call(
                trace_id=trace_id,
                tool_name=name,
                input_json=input_json,
                output_json={
                    "status": "failed",
                    "display_text": "",
                    "data": None,
                    "error": str(e),
                },
                status="failed",
                latency_ms=latency,
            )
            return ToolResult(
                tool_name=name, status="failed", display_text="", latency_ms=latency
            )
