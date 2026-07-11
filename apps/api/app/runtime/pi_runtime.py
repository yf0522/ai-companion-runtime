"""Pi production agent runtime — risk → analyzers → A2a fast-reply race ∥ sidecar FC."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
from nanoid import generate as nanoid

from app.config.settings import settings
from app.runtime.agent_runtime import RUNTIME_PI
from app.runtime.analyzers import (
    FAST_REPLY_BUDGET_MS,
    build_personality_system_prompt,
    enqueue_post_process,
    fast_reply_race,
    record_analyzer_events,
    run_analyzer_chain,
)
from app.runtime.risk_gate import run_risk_gate
from app.runtime.stream_manager import StreamManager

logger = logging.getLogger(__name__)

_SIDECAR_TIMEOUT_S = 120.0
_SIDECAR_DOWN_MSG = (
    "助手服务暂时不可用，请稍后再试。"
    "风险检测已生效；当前不会改用其他运行时。"
)
_PI_DISABLED_MSG = (
    "Pi Agent 运行时尚未在本环境启用。"
    "请部署 pi-sidecar 并确认健康检查通过后再试。"
    "不会回退到 Harness。"
)


class PiExperimentalRuntime:
    """Production Pi path — risk gate, analyzer parity, A2a fast-reply, sidecar FC."""

    name = RUNTIME_PI

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

        # Analyzer parity (intent/emotion/personality); reflection = async enqueue later.
        bundle = await run_analyzer_chain(
            user_id=user_id,
            session_id=session_id,
            message=message,
            trace_id=gate.trace_id,
            include_memory=True,
        )
        asyncio.create_task(
            record_analyzer_events(
                trace_id=gate.trace_id,
                user_id=user_id,
                session_id=session_id,
                intent=bundle.intent,
                emotion=bundle.emotion,
                personality=bundle.personality,
                latency_ms=bundle.latency_ms,
                risk=gate.risk,
                memory=bundle.memory,
            )
        )

        if not settings.enable_pi_runtime:
            return await self._emit_fail_closed(
                stream_mgr,
                gate.trace_id,
                start,
                text=_PI_DISABLED_MSG,
                error_code="pi_not_enabled",
            )

        # A2a: race first_reply in parallel with sidecar tool loop (不等待工具).
        fast_task = asyncio.create_task(
            fast_reply_race(
                message,
                bundle.emotion,
                bundle.personality,
                stream_mgr,
                start,
                cancel_event,
                budget_ms=FAST_REPLY_BUDGET_MS,
                trace_id=gate.trace_id,
                user_id=user_id,
            )
        )
        system_prompt = build_personality_system_prompt(
            bundle.personality, bundle.emotion, bundle.intent
        )

        try:
            result = await self._run_sidecar(
                user_id=user_id,
                session_id=session_id,
                message=message,
                stream_mgr=stream_mgr,
                cancel_event=cancel_event,
                trace_id=gate.trace_id,
                start=start,
                risk_level=getattr(gate.risk, "level", None),
                system_prompt=system_prompt,
                fast_task=fast_task,
            )
        except Exception as exc:
            logger.warning("Pi sidecar failed (fail-closed, no harness): %s", exc, exc_info=True)
            if not fast_task.done():
                fast_task.cancel()
            return await self._emit_fail_closed(
                stream_mgr,
                gate.trace_id,
                start,
                text=_SIDECAR_DOWN_MSG,
                error_code="sidecar_unavailable",
                detail=str(exc)[:200],
            )

        # Reflection / memory post-process — async enqueue parity (A1).
        response_text = str(result.get("response_text") or "")
        enqueue_meta = await enqueue_post_process(
            user_id=user_id,
            session_id=session_id,
            user_message=message,
            ai_response=response_text,
        )
        result["post_process"] = enqueue_meta
        result["analyzer"] = {
            "intent": bundle.intent.primary_intent,
            "emotion": bundle.emotion.emotion,
            "personality_tone": bundle.personality.tone,
            "latency_ms": bundle.latency_ms,
        }
        return result

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
        system_prompt: str | None = None,
        fast_task: asyncio.Task | None = None,
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
            "system": system_prompt or "",
        }

        response_text = ""
        first_token_from_sidecar = False
        ttft_ms = 0
        fast_reply_sent = False
        fast_ttft: int | None = None
        sidecar_error: str | None = None
        seen_done = False
        tools_used: list[dict] = []
        honesty_tool_results: list = []
        caretask_response_text: str | None = None
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

        async def _poll_fast_reply() -> None:
            nonlocal fast_reply_sent, fast_ttft, ttft_ms
            if fast_task is None:
                return
            try:
                sent, ms = await fast_task
                fast_reply_sent = bool(sent)
                fast_ttft = ms
                if sent and ms is not None and not ttft_ms:
                    ttft_ms = ms
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug("fast_reply task error: %s", exc)

        poll = asyncio.create_task(_poll_fast_reply())

        try:
            async with httpx.AsyncClient(timeout=_SIDECAR_TIMEOUT_S) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        raise RuntimeError(
                            f"sidecar HTTP {response.status_code}: "
                            f"{body.decode(errors='replace')[:200]}"
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
                            if not fast_reply_sent and not first_token_from_sidecar:
                                ttft_ms = int((time.monotonic() - start) * 1000)
                                first_token_from_sidecar = True
                                # Late sidecar token as first_reply only if A2a missed.
                                await stream_mgr.send_first_reply(delta, ttft_ms)
                                fast_reply_sent = True
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
                                if tool == "caretask" and status == "success":
                                    caretask_response_text = text
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
        finally:
            if not poll.done():
                await poll

        if sidecar_error:
            raise RuntimeError(sidecar_error)

        if response_text and not seen_done and not cancel_event.is_set():
            raise RuntimeError("Pi sidecar stream ended before completion")

        logger.info(
            "Pi sidecar stream complete model=%s/%s ttft=%sms sidecar=%sms chars=%d tools=%s fast=%s",
            settings.pi_provider,
            settings.pi_model,
            ttft_ms,
            int((time.monotonic() - sidecar_start) * 1000),
            len(response_text),
            tools_used,
            fast_reply_sent,
        )

        if caretask_response_text:
            response_text = caretask_response_text
        elif not response_text:
            response_text = "（暂时没有更多内容，请稍后再试。）"

        if honesty_tool_results:
            from app.tools.honesty import enforce_no_verbal_promise

            response_text = enforce_no_verbal_promise(response_text, honesty_tool_results)

        # If A2a and sidecar both missed first_reply (e.g. caretask-only), emit now.
        if not fast_reply_sent:
            ttft_ms = int((time.monotonic() - start) * 1000)
            await stream_mgr.send_first_reply(response_text, ttft_ms)
            fast_reply_sent = True

        total_latency_ms = int((time.monotonic() - start) * 1000)
        message_id = f"m_{nanoid(size=12)}"
        await stream_mgr.send_final(
            trace_id=trace_id,
            message_id=message_id,
            ttft_ms=ttft_ms or total_latency_ms,
            total_latency_ms=total_latency_ms,
            tools_used=tools_used,
            memory_updated=False,
        )
        return {
            "trace_id": trace_id,
            "message_id": message_id,
            "agent_runtime": self.name,
            "response_text": response_text,
            "tools_used": tools_used,
            "sidecar_error": sidecar_error,
            "fast_reply_sent": fast_reply_sent,
            "fast_ttft_ms": fast_ttft,
            "ttft_ms": ttft_ms,
            "ttft_budget_ms": FAST_REPLY_BUDGET_MS,
            "ttft_within_budget": bool(ttft_ms and ttft_ms <= FAST_REPLY_BUDGET_MS + 100),
        }

    async def _emit_fail_closed(
        self,
        stream_mgr: StreamManager,
        trace_id: str,
        start: float,
        *,
        text: str,
        error_code: str,
        detail: str | None = None,
    ) -> dict:
        """User-safe degrade when sidecar is down — never falls back to harness."""
        body = text if detail is None else f"{text}\n\n({detail})"
        ttft_ms = int((time.monotonic() - start) * 1000)
        await stream_mgr.send_first_reply(body, ttft_ms)
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
            "error": error_code,
            "fail_closed": True,
            "harness_fallback": False,
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
