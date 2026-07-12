from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
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
_SIDECAR_TIMEOUT_S = 120.0


class PiExperimentalRuntime:
    """Experimental Pi agent path — risk gate first, then pi-agent-core sidecar."""

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

        from app.tools.caretask_batch import detect_compound_caretask

        if detect_compound_caretask(message):
            return await self._run_caretask_batch(
                user_id=user_id,
                message=message,
                stream_mgr=stream_mgr,
                cancel_event=cancel_event,
                trace_id=gate.trace_id,
                start=start,
            )

        if not settings.enable_pi_runtime:
            return await self._emit_disabled_stub(stream_mgr, gate.trace_id, start)

        try:
            return await self._run_sidecar(
                user_id=user_id,
                session_id=session_id,
                message=message,
                stream_mgr=stream_mgr,
                cancel_event=cancel_event,
                trace_id=gate.trace_id,
                start=start,
                risk_level=getattr(gate.risk, "level", None),
            )
        except Exception as exc:
            logger.warning("Pi sidecar failed: %s", exc, exc_info=True)
            raise

    async def _run_caretask_batch(
        self,
        *,
        user_id: str,
        message: str,
        stream_mgr: StreamManager,
        cancel_event: asyncio.Event,
        trace_id: str,
        start: float,
    ) -> dict:
        """Execute compound CareTask turns without invoking Node or a model."""
        from app.tools.caretask_tool import CareTaskTool

        await stream_mgr.send_tool_status("caretask", "calling")
        result = await CareTaskTool().execute(
            {
                "action": "batch",
                "query": message,
                "user_id": user_id,
                "trace_id": trace_id,
                "idempotency_key": trace_id,
                "cancel_event": cancel_event,
            }
        )
        data = result.data or {}
        await stream_mgr.send_tool_result(
            "caretask",
            result.display_text,
            status=result.status,
            action="caretask_batch",
            candidates=data.get("candidates"),
            data=data,
        )
        ttft_ms = int((time.monotonic() - start) * 1000)
        await stream_mgr.send_first_reply(result.display_text, ttft_ms)
        total_latency_ms = int((time.monotonic() - start) * 1000)
        message_id = f"m_{nanoid(size=12)}"
        tools_used = [{"tool": "caretask", "action": "caretask_batch", "status": result.status}]
        await stream_mgr.send_final(
            trace_id=trace_id,
            message_id=message_id,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tools_used=tools_used,
            memory_updated=False,
        )
        return {
            "trace_id": trace_id,
            "message_id": message_id,
            "agent_runtime": self.name,
            "pi_experimental": True,
            "response_text": result.display_text,
            "tools_used": tools_used,
        }

    async def _run_sidecar(
        self,
        *,
        user_id: str,
        session_id: str,
        message: str,
        stream_mgr: StreamManager,
        cancel_event: asyncio.Event,
        trace_id: str,
        start: float,
        risk_level: str | None = None,
    ) -> dict:
        url = f"{settings.pi_sidecar_url.rstrip('/')}/v1/chat"
        payload = {
            "messages": [{"role": "user", "content": message}],
            "stream": True,
            "provider": settings.pi_provider,
            "model": settings.pi_model,
            "trace_id": trace_id,
            "user_id": user_id,
            "session_id": session_id,
            "use_agent_core": True,
            "risk_level": risk_level,
            "risk_blocked": False,
        }

        response_text = ""
        first_token = True
        ttft_ms = 0
        sidecar_error: str | None = None
        seen_done = False
        tools_used: list[dict] = []
        honesty_tool_results: list = []
        authoritative_tool_response_text: str | None = None
        sidecar_start = time.monotonic()

        def _upsert_tool(
            tool: str,
            status: str,
            action: str | None = None,
            *,
            candidates: list | None = None,
            clarify_verb: str | None = None,
        ) -> None:
            if not tool:
                return
            entry: dict = {"tool": tool, "status": status}
            if action:
                entry["action"] = action
            if candidates and status == "needs_clarification":
                entry["candidates"] = candidates
            if clarify_verb:
                entry["clarify_verb"] = clarify_verb
            for i, existing in enumerate(tools_used):
                if existing.get("tool") == tool:
                    # Preserve clarify payload if a later done/status event omits it.
                    if "candidates" not in entry and existing.get("candidates"):
                        entry["candidates"] = existing["candidates"]
                    if "clarify_verb" not in entry and existing.get("clarify_verb"):
                        entry["clarify_verb"] = existing["clarify_verb"]
                    tools_used[i] = entry
                    return
            tools_used.append(entry)

        def _record_honesty_result(
            tool: str,
            status: str,
            display_text: str = "",
            action: str | None = None,
        ) -> None:
            from app.tools.base import ToolResult

            data = {"action": action} if action else None
            honesty_tool_results.append(
                ToolResult(
                    tool_name=tool,
                    status=status,
                    display_text=display_text,
                    data=data,
                )
            )

        async with httpx.AsyncClient(timeout=_SIDECAR_TIMEOUT_S) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise RuntimeError(
                        f"sidecar HTTP {response.status_code}: {body.decode(errors='replace')[:200]}"
                    )

                async for line in response.aiter_lines():
                    if cancel_event.is_set():
                        break
                    if stream_mgr.dead:
                        sidecar_error = sidecar_error or "websocket disconnected during Pi stream"
                        break
                    if not line:
                        continue

                    event = _parse_sidecar_event(line)
                    if event is None:
                        continue

                    event_type = event.get("type")
                    if event_type == "text_delta":
                        delta = str(event.get("delta", ""))
                        if not delta:
                            continue
                        if first_token:
                            ttft_ms = int((time.monotonic() - start) * 1000)
                            first_token = False
                        response_text += delta
                    elif event_type == "tool_status":
                        tool = str(event.get("tool", "caretask"))
                        status = str(event.get("status", "calling"))
                        await stream_mgr.send_tool_status(tool, status)
                        _upsert_tool(tool, status)
                        if status in {"failed", "timeout", "needs_clarification"}:
                            _record_honesty_result(
                                tool,
                                status,
                                display_text=(
                                    "需要确认具体任务"
                                    if status == "needs_clarification"
                                    else f"{tool} 未能完成"
                                ),
                            )
                    elif event_type == "tool_result":
                        tool = str(event.get("tool", "caretask"))
                        text = str(event.get("text", ""))
                        status = str(event.get("status", "success"))
                        action = event.get("action")
                        candidates = event.get("candidates")
                        event_data = event.get("data")
                        if text:
                            await stream_mgr.send_tool_result(
                                tool,
                                text,
                                status=status,
                                action=str(action) if action else None,
                                candidates=candidates if isinstance(candidates, list) else None,
                                data=event_data if isinstance(event_data, dict) else None,
                            )
                            if (
                                (tool == "caretask" and status == "success")
                                or tool == "contact"
                            ):
                                authoritative_tool_response_text = text
                        clarify_verb = None
                        if isinstance(event_data, dict):
                            clarify_verb = event_data.get("clarify_verb")
                        _upsert_tool(
                            tool,
                            status,
                            str(action) if action else None,
                            candidates=candidates if isinstance(candidates, list) else None,
                            clarify_verb=str(clarify_verb) if clarify_verb else None,
                        )
                        if status in {"failed", "timeout", "needs_clarification"}:
                            _record_honesty_result(
                                tool,
                                status,
                                display_text=text or f"{tool} 未能完成",
                                action=str(action) if action else None,
                            )
                        elif status == "success" and (
                            action in {"caretask_reuse", "caretask_schedule_updated"}
                            or "没有重复创建" in text
                            or "帮您沿用" in text
                            or "未重复创建" in text
                            or "已有相同" in text
                        ):
                            _record_honesty_result(
                                tool,
                                status,
                                display_text=text,
                                action=str(action)
                                if action
                                else (
                                    "caretask_reuse"
                                    if (
                                        "没有重复创建" in text
                                        or "帮您沿用" in text
                                        or "未重复创建" in text
                                    )
                                    else None
                                ),
                            )
                    elif event_type == "error":
                        sidecar_error = str(event.get("message", "pi sidecar error"))
                        break
                    elif event_type == "done":
                        for item in event.get("tools_used") or []:
                            if isinstance(item, dict):
                                _upsert_tool(
                                    str(item.get("tool") or ""),
                                    str(item.get("status") or "success"),
                                    str(item["action"]) if item.get("action") else None,
                                )
                            elif item:
                                _upsert_tool(str(item), "success")
                        seen_done = True
                        break

        if sidecar_error:
            raise RuntimeError(sidecar_error)

        if response_text and not seen_done and not cancel_event.is_set():
            raise RuntimeError("Pi sidecar stream ended before completion")

        logger.info(
            "Pi sidecar stream complete model=%s/%s ttft=%sms sidecar=%sms chars=%d tools=%s",
            settings.pi_provider,
            settings.pi_model,
            ttft_ms,
            int((time.monotonic() - sidecar_start) * 1000),
            len(response_text),
            tools_used,
        )

        if authoritative_tool_response_text:
            response_text = authoritative_tool_response_text
        elif not response_text:
            response_text = "（Pi 实验路径未返回内容，请稍后重试。）"

        if honesty_tool_results:
            from app.tools.honesty import enforce_no_verbal_promise

            honest = enforce_no_verbal_promise(response_text, honesty_tool_results)
            response_text = honest

        if first_token or authoritative_tool_response_text:
            ttft_ms = int((time.monotonic() - start) * 1000)
        await stream_mgr.send_first_reply(response_text, ttft_ms)

        total_latency_ms = int((time.monotonic() - start) * 1000)
        message_id = f"m_{nanoid(size=12)}"
        await stream_mgr.send_final(
            trace_id=trace_id,
            message_id=message_id,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tools_used=tools_used,
            memory_updated=False,
        )
        return {
            "trace_id": trace_id,
            "message_id": message_id,
            "agent_runtime": self.name,
            "pi_experimental": True,
            "response_text": response_text,
            "tools_used": tools_used,
            "sidecar_error": sidecar_error,
            # Tradeoff note: pi-agent-core tool loop may increase TTFT vs harness fast-reply.
            "ttft_tradeoff": "pi_agent_core_tool_loop_may_delay_first_token_vs_harness_fast_reply",
        }

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


def _parse_sidecar_event(line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        logger.debug("Skipping non-JSON sidecar line")
        return None
    if isinstance(payload, dict):
        return payload
    return None
