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
        from app.tools.registry import get_tool_registry

        for tool in get_tool_registry().values():
            self.register(tool)

    def register(self, tool: ToolBase):
        self._tools[tool.name] = tool

    async def dispatch(
        self,
        tool_needs: list[str],
        message: str,
        trace_id: str,
        stream_mgr: StreamManager,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> list[ToolResult]:
        tasks = []
        for name in tool_needs[: self._max_tool_calls]:
            if name in self._tools:
                tasks.append(
                    self._call_tool(
                        name,
                        message,
                        trace_id,
                        stream_mgr,
                        user_id=user_id,
                        session_id=session_id,
                    )
                )
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
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> ToolResult:
        tool = self._tools[name]
        await stream_mgr.send_tool_status(name, "calling")
        start = time.monotonic()
        params = {
            "query": message,
            "user_id": user_id,
            "session_id": session_id,
            "trace_id": trace_id,
        }
        input_json = {
            "query": message,
            "user_id": user_id,
            "session_id": session_id,
        }

        try:
            result = await asyncio.wait_for(
                tool.execute(params),
                timeout=self._tool_timeout_ms / 1000,
            )
            latency = int((time.monotonic() - start) * 1000)
            result.latency_ms = latency

            if result.data and result.data.get("action"):
                action = result.data["action"]
                if action in {"reminder_create", "reminder_snooze"}:
                    ws_data = {
                        k: v
                        for k, v in result.data.items()
                        if k not in ("action", "display_time")
                    }
                    if action == "reminder_create":
                        await stream_mgr.send_reminder_create(ws_data)
                    else:
                        await stream_mgr.send_reminder_snooze(ws_data)
                elif action == "caretask_snooze" and isinstance(result.data.get("task"), dict):
                    task = result.data["task"]
                    await stream_mgr.send_reminder_snooze(
                        {
                            "reminder_id": task.get("reminder_id"),
                            "label": task.get("title"),
                            "snooze_minutes": result.data.get("snooze_minutes"),
                            "next_fire_at": task.get("snooze_until") or task.get("due_at"),
                        }
                    )

            if result.status == "success":
                await stream_mgr.send_tool_status(name, "success")
                await stream_mgr.send_tool_result(name, result.display_text)
            elif result.status == "needs_clarification":
                await stream_mgr.send_tool_status(name, "needs_clarification")
                if result.display_text:
                    await stream_mgr.send_tool_result(name, result.display_text)
            else:
                await stream_mgr.send_tool_status(name, result.status or "failed")
                if result.display_text:
                    await stream_mgr.send_tool_result(name, result.display_text)

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
