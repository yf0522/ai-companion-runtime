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
                await self._project_device_events(action, result.data, stream_mgr)

            result_data = result.data if isinstance(result.data, dict) else {}
            candidates = result_data.get("candidates") if result_data else None
            action = result_data.get("action") if result_data else None
            if result.status == "success":
                await stream_mgr.send_tool_status(name, "success")
                await stream_mgr.send_tool_result(
                    name,
                    result.display_text,
                    status="success",
                    action=action,
                    data=result_data or None,
                )
            elif result.status == "needs_clarification":
                await stream_mgr.send_tool_status(name, "needs_clarification")
                if result.display_text:
                    await stream_mgr.send_tool_result(
                        name,
                        result.display_text,
                        status="needs_clarification",
                        action=action,
                        candidates=candidates,
                        data=result_data or None,
                    )
            else:
                await stream_mgr.send_tool_status(name, result.status or "failed")
                if result.display_text:
                    await stream_mgr.send_tool_result(
                        name,
                        result.display_text,
                        status=result.status or "failed",
                        action=action,
                        data=result_data or None,
                    )

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

    async def _project_device_events(
        self,
        action: str,
        data: dict,
        stream_mgr: StreamManager,
    ) -> None:
        """Map domain tool actions onto device-consumable reminder_* events."""
        from app.tools.device_projection import (
            caretask_device_cancel_payload,
            caretask_device_create_payload,
            caretask_device_snooze_payload,
        )

        if action in {"reminder_create", "reminder_snooze"}:
            ws_data = {
                k: v
                for k, v in data.items()
                if k not in ("action", "display_time")
            }
            if action == "reminder_create":
                await stream_mgr.send_reminder_create(ws_data)
            else:
                await stream_mgr.send_reminder_snooze(ws_data)
            return

        task = data.get("task") if isinstance(data.get("task"), dict) else None

        if action in {
            "caretask_create",
            "caretask_reuse",
            "caretask_schedule_updated",
        }:
            if not task:
                return
            # Skip device create on plain reuse without schedule change (no new timer).
            if action == "caretask_reuse" and not data.get("schedule_updated"):
                return
            payload = caretask_device_create_payload(
                task,
                schedule_type=data.get("schedule_type") or task.get("schedule_type"),
                query=data.get("query"),
            )
            if payload:
                await stream_mgr.send_reminder_create(payload)
            return

        if action == "caretask_snooze":
            payload = caretask_device_snooze_payload(data)
            if payload:
                await stream_mgr.send_reminder_snooze(payload)
            return

        if action in {"caretask_complete", "caretask_cancel"}:
            if not task:
                return
            payload = caretask_device_cancel_payload(task)
            if payload:
                await stream_mgr.send_reminder_cancel(payload)
            return
