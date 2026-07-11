from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import yaml
from nanoid import generate as nanoid

from app.engines.base import (
    AnalyzerInput, IntentResult, EmotionResult, RiskResult,
    MemorySnapshot, PersonalityConfig,
)
from app.runtime.analyzers import (
    analyzer_timeout_ms,
    enqueue_post_process,
    fast_reply_race,
    get_cached_engine,
    get_personality,
    record_analyzer_events,
    run_intent_emotion_memory,
    stable_uuid,
)
from app.runtime.stream_manager import StreamManager
from app.observability.trace_service import TraceService

logger = logging.getLogger(__name__)
_trace_svc = TraceService()


_harness_config: dict | None = None


def _load_harness_config() -> dict:
    global _harness_config
    if _harness_config is not None:
        return _harness_config
    path = Path(__file__).parent.parent / "config" / "harness.yaml"
    try:
        with open(path) as f:
            _harness_config = yaml.safe_load(f).get("harness", {})
    except Exception as exc:
        logger.warning("Failed to load harness.yaml: %s, using defaults", exc)
        _harness_config = {}
    return _harness_config


async def _record_analysis_events(
    *,
    trace_id: str,
    user_id: str,
    session_id: str,
    intent: IntentResult,
    emotion: EmotionResult,
    risk: RiskResult,
    memory: MemorySnapshot,
    latency_ms: int,
) -> None:
    # user_id/session_id already stable UUIDs from harness callers.
    personality = PersonalityConfig()
    await record_analyzer_events(
        trace_id=trace_id,
        user_id=user_id,
        session_id=session_id,
        intent=intent,
        emotion=emotion,
        personality=personality,
        latency_ms=latency_ms,
        risk=risk,
        memory=memory,
    )


def _stable_uuid(value: str) -> str:
    return stable_uuid(value)


def _get_cached_engine(name: str):
    return get_cached_engine(name)


class AgentHarness:
    """Orchestrates the full request pipeline with timeouts, retries, and fallback."""

    def __init__(self):
        self._config = _load_harness_config()

    @property
    def max_steps(self) -> int:
        return self._config.get("max_steps", 5)

    @property
    def max_retries(self) -> int:
        return self._config.get("max_retries", 2)

    @property
    def max_tool_calls(self) -> int:
        return self._config.get("max_tool_calls", 3)

    def _timeout(self, key: str) -> int:
        return self._config.get("timeouts", {}).get(key, 5000)

    def _template(self, key: str) -> str:
        return self._config.get("templates", {}).get(key, "")

    async def run(
        self,
        user_id: str,
        session_id: str,
        message: str,
        stream_mgr: StreamManager,
        cancel_event: asyncio.Event,
    ) -> dict:
        """Execute the full pipeline. Returns metadata dict."""
        db_user_id = _stable_uuid(user_id)
        db_session_id = _stable_uuid(session_id)

        start_time = time.monotonic()
        trace_id = self._generate_trace_id(user_id)

        await stream_mgr.send_trace(trace_id)

        analyzer_input = AnalyzerInput(
            user_id=user_id, session_id=session_id,
            message=message, trace_id=trace_id,
        )
        intent, emotion, risk, memory = await self._run_analyzers(analyzer_input)

        analyzer_ms = int((time.monotonic() - start_time) * 1000)

        if risk.level in ("critical", "high"):
            analysis_trace = asyncio.create_task(
                _record_analysis_events(
                    trace_id=trace_id,
                    user_id=db_user_id,
                    session_id=db_session_id,
                    intent=intent,
                    emotion=emotion,
                    risk=risk,
                    memory=memory,
                    latency_ms=analyzer_ms,
                )
            )
            await self._handle_risk(
                risk,
                stream_mgr,
                trace_id,
                start_time,
                user_id,
                session_id,
                analysis_trace,
            )
            return {"trace_id": trace_id, "blocked_by_risk": True}

        asyncio.create_task(
            _record_analysis_events(
                trace_id=trace_id,
                user_id=db_user_id,
                session_id=db_session_id,
                intent=intent,
                emotion=emotion,
                risk=risk,
                memory=memory,
                latency_ms=analyzer_ms,
            )
        )

        if risk.level == "medium":
            await self._dispatch_risk_notification(
                user_id,
                "medium",
                risk.category,
                self._build_family_notification_summary(risk),
                trace_id,
            )

        if "caretask" in intent.tool_needs:
            return await self._run_deterministic_caretask(
                message=message,
                trace_id=trace_id,
                stream_mgr=stream_mgr,
                user_id=db_user_id,
                session_id=db_session_id,
                start_time=start_time,
            )

        personality = await self._get_personality(emotion, intent)

        fast_reply_sent = await self._fast_reply_race(
            message, emotion, personality, stream_mgr, start_time, cancel_event,
        )

        if cancel_event.is_set():
            return {"trace_id": trace_id, "cancelled": True}

        ttft_ms = None
        response_text = ""
        tool_results = []
        message_id = f"m_{nanoid(size=12)}"

        from app.runtime.prompt_builder import PromptBuilder
        prompt_builder = PromptBuilder()
        messages = prompt_builder.build(
            user_message=message,
            intent=intent,
            emotion=emotion,
            personality=personality,
            memory=memory,
        )

        tool_task = None
        if intent.tool_needs and not cancel_event.is_set():
            tool_task = asyncio.create_task(
                self._dispatch_tools(
                    intent.tool_needs,
                    message,
                    trace_id,
                    stream_mgr,
                    user_id=db_user_id,
                    session_id=db_session_id,
                )
            )

        model_total_timeout = self._timeout("model_total") / 1000
        retries = 0
        model_success = False
        model_provider = "unknown"
        model_name = "unknown"
        model_role = "primary"
        last_model = None
        while retries <= self.max_retries and not cancel_event.is_set():
            try:
                model_role = "primary" if retries == 0 else "fallback"
                from app.models.router import model_router
                model = await model_router.get_model(model_role)
                last_model = model
                model_provider = getattr(model, "provider", "unknown") or "unknown"
                model_name = getattr(model, "model_name", "unknown") or "unknown"
                first_token = True

                async def _stream_model():
                    nonlocal first_token, ttft_ms, fast_reply_sent, response_text
                    async for token in model.stream_chat(messages):
                        if cancel_event.is_set() or stream_mgr.dead:
                            break
                        if first_token:
                            if not fast_reply_sent:
                                ttft_ms = int((time.monotonic() - start_time) * 1000)
                                await stream_mgr.send_first_reply(token, ttft_ms)
                            else:
                                await stream_mgr.send_delta(token)
                            first_token = False
                        else:
                            await stream_mgr.send_delta(token)
                        response_text += token

                await asyncio.wait_for(_stream_model(), timeout=model_total_timeout)
                model_success = True
                break

            except asyncio.TimeoutError:
                logger.warning(f"Model stream timed out after {model_total_timeout}s")
                retries += 1
                if retries > self.max_retries:
                    break
            except Exception as exc:
                retries += 1
                logger.warning("Model attempt %s failed: %s", retries, exc)
                if retries > self.max_retries:
                    break

        if not model_success:
            fallback_text = self._template("model_all_fail") or "抱歉，我现在有点反应不过来，你能稍后再试一下吗？"
            if not fast_reply_sent:
                ttft_ms = int((time.monotonic() - start_time) * 1000)
                await stream_mgr.send_first_reply(fallback_text, ttft_ms)
            else:
                await stream_mgr.send_delta(fallback_text)
            response_text = fallback_text

        if tool_task:
            try:
                tool_results = await asyncio.wait_for(tool_task, timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning("Tool dispatch did not finish in time after model stream")
                tool_results = []
            except Exception as exc:
                logger.warning("Tool dispatch failed: %s", exc)
                tool_results = []

        # Contract: never let the model verbally promise success after a failed tool,
        # or invent "created / reminded now" when CareTask only reused.
        from app.tools.honesty import enforce_no_verbal_promise

        honest_text = enforce_no_verbal_promise(response_text, tool_results)
        if honest_text != response_text:
            logger.info("Rewrote response for tool honesty (fail/clarify/reuse)")
            await stream_mgr.send_delta("\n" + honest_text)
            response_text = honest_text

        total_latency_ms = int((time.monotonic() - start_time) * 1000)
        tools_used: list[dict] = []
        for t in tool_results or []:
            if isinstance(t, dict):
                name = t.get("tool_name", "")
                status = t.get("status", "success")
                data = t.get("data") if isinstance(t.get("data"), dict) else {}
                action = data.get("action") if data else None
                candidates = data.get("candidates") if data else None
            elif hasattr(t, "tool_name"):
                name = t.tool_name
                status = getattr(t, "status", "success")
                data = getattr(t, "data", None) or {}
                action = data.get("action") if isinstance(data, dict) else None
                candidates = data.get("candidates") if isinstance(data, dict) else None
            else:
                continue
            if not name:
                continue
            entry: dict = {"tool": name, "status": status}
            if action:
                entry["action"] = action
            if candidates and status == "needs_clarification":
                entry["candidates"] = candidates
                if isinstance(data, dict) and data.get("clarify_verb"):
                    entry["clarify_verb"] = data["clarify_verb"]
            tools_used.append(entry)

        prompt_tokens = 0
        output_tokens = 0
        if last_model is not None and hasattr(last_model, "count_tokens"):
            try:
                prompt_tokens = sum(
                    int(last_model.count_tokens(m.get("content", "") or ""))
                    for m in messages
                )
                output_tokens = int(last_model.count_tokens(response_text or ""))
            except Exception as exc:
                logger.debug("Token counting skipped: %s", exc)

        asyncio.create_task(_trace_svc.record_model_call(
            trace_id=trace_id,
            provider=model_provider,
            model=model_name,
            role=model_role,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            ttft_ms=ttft_ms or 0,
            total_latency_ms=total_latency_ms,
            status="success" if model_success else "failed",
        ))

        asyncio.create_task(_trace_svc.add_event(
            trace_id=trace_id, step_name="model_stream", step_index=8,
            user_id=db_user_id, session_id=db_session_id,
            output_json={
                "response_length": len(response_text),
                "model_success": model_success,
                "provider": model_provider,
                "model": model_name,
                "role": model_role,
            },
            status="success" if model_success else "failed",
            latency_ms=total_latency_ms,
        ))

        asyncio.create_task(_trace_svc.add_event(
            trace_id=trace_id, step_name="response_final", step_index=10,
            user_id=db_user_id, session_id=db_session_id,
            output_json={"ttft_ms": ttft_ms, "total_latency_ms": total_latency_ms, "tools_used": tools_used},
            status="success", latency_ms=total_latency_ms,
        ))

        await stream_mgr.send_final(
            trace_id=trace_id,
            message_id=message_id,
            ttft_ms=ttft_ms or 0,
            total_latency_ms=total_latency_ms,
            tools_used=tools_used,
            memory_updated=True,
        )

        await self._persist_conversation(
            session_id, user_id, message, response_text,
        )

        return {
            "trace_id": trace_id,
            "message_id": message_id,
            "ttft_ms": ttft_ms,
            "total_latency_ms": total_latency_ms,
        }

    async def _run_deterministic_caretask(
        self,
        *,
        message: str,
        trace_id: str,
        stream_mgr: StreamManager,
        user_id: str,
        session_id: str,
        start_time: float,
    ) -> dict:
        """Use backend CareTask copy as the single elder-facing response."""
        results = await self._dispatch_tools(
            ["caretask"],
            message,
            trace_id,
            stream_mgr,
            user_id=user_id,
            session_id=session_id,
        )
        result = results[0] if results else None
        response_text = getattr(result, "display_text", "") or "照护任务暂时无法处理，请稍后再试。"
        status = getattr(result, "status", "failed")
        data = getattr(result, "data", None) or {}
        tool_entry: dict = {"tool": "caretask", "status": status}
        if action := data.get("action"):
            tool_entry["action"] = action
        if candidates := data.get("candidates"):
            tool_entry["candidates"] = candidates
            if clarify_verb := data.get("clarify_verb"):
                tool_entry["clarify_verb"] = clarify_verb

        ttft_ms = int((time.monotonic() - start_time) * 1000)
        await stream_mgr.send_first_reply(response_text, ttft_ms)
        total_latency_ms = int((time.monotonic() - start_time) * 1000)
        message_id = f"m_{nanoid(size=12)}"
        await stream_mgr.send_final(
            trace_id=trace_id,
            message_id=message_id,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tools_used=[tool_entry],
            memory_updated=True,
        )
        await self._persist_conversation(session_id, user_id, message, response_text)
        return {
            "trace_id": trace_id,
            "message_id": message_id,
            "ttft_ms": ttft_ms,
            "total_latency_ms": total_latency_ms,
            "deterministic_caretask": True,
        }

    async def _run_analyzers(self, input: AnalyzerInput) -> tuple:
        """Run all analyzers in parallel with individual timeouts (shared module)."""
        timeout_ms = analyzer_timeout_ms("analyzer")

        async def _safe_risk(default: RiskResult) -> RiskResult:
            try:
                engine = self._get_engine("risk")
                if engine:
                    return await asyncio.wait_for(
                        engine.analyze(input),
                        timeout=timeout_ms / 1000,
                    )
            except asyncio.TimeoutError:
                logger.warning("risk timed out (%sms)", timeout_ms)
            except Exception as e:
                logger.warning("risk failed: %s", e)
            return RiskResult(
                level="critical",
                category="safety_unavailable",
                confidence=1.0,
                triggered_rules=["risk_engine_unavailable"],
            )

        intent, emotion, memory = await run_intent_emotion_memory(input, include_memory=True)
        risk = await _safe_risk(RiskResult())
        return intent, emotion, risk, memory

    def _get_engine(self, name: str):
        return _get_cached_engine(name)

    async def _handle_risk(
        self,
        risk: RiskResult,
        stream_mgr: StreamManager,
        trace_id: str,
        start_time: float,
        user_id: str,
        session_id: str | None = None,
        analysis_trace: asyncio.Task | None = None,
    ):
        """Handle high/critical risk: send alert and safe response."""
        from app.runtime.risk_gate import build_safety_response, load_safety_message

        summary = self._build_family_notification_summary(risk)
        notify_status = await self._dispatch_risk_notification(
            user_id,
            risk.level,
            risk.category,
            summary,
            trace_id,
        )
        safety_msg = build_safety_response(
            load_safety_message(risk.level, risk.category),
            notify_status,
        )
        # Level-only alert: safety copy goes once via first_reply (avoid bubble dup).
        await stream_mgr.send_risk_alert(risk.level, "")

        ttft_ms = int((time.monotonic() - start_time) * 1000)
        await stream_mgr.send_first_reply(safety_msg, ttft_ms)

        total_latency_ms = int((time.monotonic() - start_time) * 1000)
        await _trace_svc.add_event(
            trace_id=trace_id,
            step_name="family_notification",
            step_index=4,
            user_id=_stable_uuid(user_id),
            output_json=notify_status,
            status=(
                "success"
                if notify_status.get("status") in {"persisted", "queued"}
                else "failed"
            ),
        )

        if analysis_trace is not None:
            await analysis_trace
        await _trace_svc.add_event(
            trace_id=trace_id,
            step_name="risk_response_final",
            step_index=10,
            user_id=_stable_uuid(user_id),
            session_id=_stable_uuid(session_id) if session_id else None,
            output_json={
                "risk_level": risk.level,
                "risk_category": risk.category,
                "ttft_ms": ttft_ms,
                "total_latency_ms": total_latency_ms,
                "notification_status": notify_status.get("status"),
            },
            status="success",
            latency_ms=total_latency_ms,
            required=True,
        )
        await stream_mgr.send_final(
            trace_id=trace_id,
            message_id=f"m_{nanoid(size=12)}",
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tools_used=[],
            memory_updated=False,
        )

    async def _dispatch_risk_notification(
        self,
        user_id: str,
        risk_level: str,
        risk_category: str | None,
        summary: str,
        trace_id: str,
    ) -> dict:
        try:
            from app.config.settings import settings
            from app.workers.notification_outbox_worker import (
                create_safety_notification_pipeline,
                deliver_notification_outbox,
            )
            result = await create_safety_notification_pipeline(
                user_id=_stable_uuid(user_id),
                risk_level=risk_level,
                risk_category=risk_category or "unknown",
                summary=summary,
                trace_id=trace_id,
            )
            if settings.enable_celery_tasks and result.get("outbox_ids"):
                deliver_notification_outbox.delay()
                result["delivery_queued"] = True
            return result
        except Exception as exc:
            logger.error("Notification dispatch failed: %s", exc)
            return {
                "status": "failed",
                "records": 0,
                "webhook_status": None,
                "error": str(exc),
            }

    def _build_family_notification_summary(self, risk: RiskResult) -> str:
        if risk.category == "scam_alert":
            keyword_text = " ".join(
                r.replace("keyword:", "").replace("pattern:", "")
                for r in (risk.triggered_rules or [])
            )
            if "验证码" in keyword_text:
                return "疑似反诈：检测到验证码索要行为，建议先电话确认，不要转账、不报验证码。"
            if "转账" in keyword_text or "汇款" in keyword_text:
                return "疑似反诈：检测到可疑转账/汇款风险，建议先与家属或官方确认，再执行任何转账。"
            return "疑似反诈：检测到可疑理财/支付引导，建议先电话确认，避免立即付款。"

        if risk.category == "health_emergency":
            return "高危健康信号：检测到胸闷/头晕/呼吸困难类风险，建议立即联系家属并协助就医。"

        if risk.category == "emotional_crisis":
            return "情绪危机：检测到自杀意念相关表述，请尽快联系老人并确认安全。"

        if risk.category == "emotional_low":
            return "用户情绪偏低：建议家属主动关怀并保持持续陪伴，观察言语变化。"

        if risk.level in {"high", "critical"}:
            return "检测到高风险行为，建议先与家属确认后再处理后续动作。"

        return "检测到中等风险内容，请关注并适时回访。"

    async def _fast_reply_race(
        self, message: str, emotion: EmotionResult, personality: PersonalityConfig,
        stream_mgr: StreamManager, start_time: float, cancel_event: asyncio.Event,
    ) -> bool:
        """Delegate to shared A2a fast-reply helper."""
        sent, _ttft = await fast_reply_race(
            message, emotion, personality, stream_mgr, start_time, cancel_event,
            budget_ms=self._timeout("fast_reply"),
        )
        return sent

    async def _dispatch_tools(
        self,
        tool_needs: list[str],
        message: str,
        trace_id: str,
        stream_mgr: StreamManager,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> list:
        """Dispatch tools with user/session context for persistence-capable tools."""
        try:
            from app.tools.dispatcher import ToolDispatcher
            dispatcher = ToolDispatcher()
            return await dispatcher.dispatch(
                tool_needs,
                message,
                trace_id,
                stream_mgr,
                user_id=user_id,
                session_id=session_id,
            )
        except ImportError:
            logger.debug("ToolDispatcher unavailable")
            return []

    async def _get_personality(self, emotion: EmotionResult, intent=None) -> PersonalityConfig:
        """Get personality config using shared analyzer helper."""
        return await get_personality(emotion, intent)

    async def _persist_conversation(
        self, session_id: str, user_id: str, user_message: str, ai_response: str,
    ):
        """L0 persist + Celery memory/reflection enqueue (shared post-process)."""
        await enqueue_post_process(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
            ai_response=ai_response,
        )

    def _generate_trace_id(self, user_id: str) -> str:
        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d")
        uid_short = user_id[:8] if len(user_id) > 8 else user_id
        return f"trace_{date_str}_{uid_short}_{nanoid(size=8)}"
