from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

import yaml
from nanoid import generate as nanoid

from app.engines.base import (
    AnalyzerInput, IntentResult, EmotionResult, RiskResult,
    MemorySnapshot, PersonalityConfig,
)
from app.runtime.stream_manager import StreamManager
from app.observability.trace_service import TraceService

logger = logging.getLogger(__name__)
_trace_svc = TraceService()
_RISK_NOTIFICATION_TIMEOUT_S = 0.25
_RISK_TRACE_TIMEOUT_S = 0.25


_harness_config: dict | None = None


async def _cancel_and_drain(task: asyncio.Task | None) -> None:
    if task is None:
        return
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def _load_harness_config() -> dict:
    global _harness_config
    if _harness_config is not None:
        return _harness_config
    path = Path(__file__).parent.parent / "config" / "harness.yaml"
    try:
        with open(path) as f:
            _harness_config = yaml.safe_load(f).get("harness", {})
    except Exception as exc:
        logger.warning(
            "Harness config load failed error_class=%s code=harness_config_load_failed",
            type(exc).__name__,
        )
        _harness_config = {}
    return _harness_config


_engine_cache: dict[str, object] = {}


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
    await asyncio.gather(
        _trace_svc.add_event(
            trace_id=trace_id,
            step_name="intent_detection",
            step_index=1,
            user_id=user_id,
            session_id=session_id,
            output_json=intent.model_dump(),
            status="success",
            latency_ms=latency_ms,
        ),
        _trace_svc.add_event(
            trace_id=trace_id,
            step_name="emotion_detection",
            step_index=2,
            user_id=user_id,
            session_id=session_id,
            output_json=emotion.model_dump(),
            status="success",
            latency_ms=latency_ms,
        ),
        _trace_svc.add_event(
            trace_id=trace_id,
            step_name="risk_detection",
            step_index=3,
            user_id=user_id,
            session_id=session_id,
            output_json={
                "level": risk.level,
                "category": risk.category,
                "confidence": risk.confidence,
                "triggered_rule_types": sorted({
                    str(rule).partition(":")[0][:40]
                    for rule in (risk.triggered_rules or [])
                }),
            },
            status="success",
            latency_ms=latency_ms,
        ),
        _trace_svc.add_event(
            trace_id=trace_id,
            step_name="memory_recall",
            step_index=4,
            user_id=user_id,
            session_id=session_id,
            output_json={
                "working_count": len(memory.working or []),
                "vector_count": len(memory.vectors or []),
                "has_summary": bool(memory.summary),
                "has_profile": bool(memory.profile),
                "profile_keys": list((memory.profile or {}).keys())[:12],
            },
            status="success",
            latency_ms=latency_ms,
        ),
    )


def _stable_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, value))


def _get_cached_engine(name: str):
    if name in _engine_cache:
        return _engine_cache[name]
    try:
        if name == "intent":
            from app.engines.intent_engine import IntentEngine
            _engine_cache[name] = IntentEngine()
        elif name == "emotion":
            from app.engines.emotion_engine import EmotionEngine
            _engine_cache[name] = EmotionEngine()
        elif name == "risk":
            from app.engines.risk_engine import RiskEngine
            _engine_cache[name] = RiskEngine()
        elif name == "memory":
            from app.engines.memory_engine import MemoryEngine
            _engine_cache[name] = MemoryEngine()
    except ImportError:
        return None
    return _engine_cache.get(name)


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
            risk_metadata = await self._handle_risk(
                risk,
                stream_mgr,
                trace_id,
                start_time,
                user_id,
                session_id,
                analysis_trace,
                message,
            )
            return {
                "trace_id": trace_id,
                "blocked_by_risk": True,
                **risk_metadata,
            }

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
            from app.runtime.risk_gate import persist_nonblocking_decision

            decision = await persist_nonblocking_decision(user_id, risk, trace_id)
            await _trace_svc.add_event(
                trace_id=trace_id,
                step_name="risk_decision_persistence",
                step_index=5,
                user_id=db_user_id,
                session_id=db_session_id,
                output_json={
                    key: decision[key]
                    for key in ("status", "error_class", "error_code")
                    if key in decision
                },
                status="success" if decision.get("status") == "persisted" else "failed",
            )

        from app.runtime.capability_response import capability_response_for

        if capability_response_for(message):
            return await self._run_deterministic_capability(
                message=message,
                trace_id=trace_id,
                stream_mgr=stream_mgr,
                user_id=user_id,
                session_id=session_id,
                start_time=start_time,
            )

        from app.tools.caretask_batch import detect_compound_caretask

        if detect_compound_caretask(message):
            return await self._run_deterministic_caretask(
                message=message,
                trace_id=trace_id,
                stream_mgr=stream_mgr,
                user_id=db_user_id,
                session_id=db_session_id,
                start_time=start_time,
            )

        if "contact" in intent.tool_needs:
            return await self._run_deterministic_contact(
                message=message,
                trace_id=trace_id,
                stream_mgr=stream_mgr,
                user_id=db_user_id,
                session_id=db_session_id,
                start_time=start_time,
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
        message_id = str(uuid.uuid4())

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
                if cancel_event.is_set():
                    await _cancel_and_drain(tool_task)
                    return {"trace_id": trace_id, "cancelled": True}
                model_success = True
                break

            except asyncio.CancelledError:
                await _cancel_and_drain(tool_task)
                raise
            except asyncio.TimeoutError:
                logger.warning(f"Model stream timed out after {model_total_timeout}s")
                retries += 1
                if retries > self.max_retries:
                    break
            except Exception as exc:
                retries += 1
                logger.warning(
                    "Model attempt failed attempt=%s error_class=%s code=model_attempt_failed",
                    retries,
                    type(exc).__name__,
                )
                if retries > self.max_retries:
                    break

        if cancel_event.is_set():
            await _cancel_and_drain(tool_task)
            return {"trace_id": trace_id, "cancelled": True}

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
            except asyncio.CancelledError:
                await _cancel_and_drain(tool_task)
                raise
            except asyncio.TimeoutError:
                logger.warning("Tool dispatch did not finish in time after model stream")
                tool_results = []
            except Exception as exc:
                logger.warning(
                    "Tool dispatch failed error_class=%s code=tool_dispatch_failed",
                    type(exc).__name__,
                )
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

        evidence_status = await self._persist_conversation(
            session_id, user_id, message, response_text,
            trace_id=trace_id, assistant_message_id=message_id,
        )

        return {
            "trace_id": trace_id,
            "message_id": message_id,
            "ttft_ms": ttft_ms,
            "total_latency_ms": total_latency_ms,
            "message_evidence": evidence_status,
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
        message_id = str(uuid.uuid4())
        await stream_mgr.send_final(
            trace_id=trace_id,
            message_id=message_id,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tools_used=[tool_entry],
            memory_updated=True,
        )
        evidence_status = await self._persist_conversation(
            session_id, user_id, message, response_text,
            trace_id=trace_id, assistant_message_id=message_id,
        )
        return {
            "trace_id": trace_id,
            "message_id": message_id,
            "ttft_ms": ttft_ms,
            "total_latency_ms": total_latency_ms,
            "deterministic_caretask": True,
            "message_evidence": evidence_status,
        }

    async def _run_deterministic_contact(
        self,
        *,
        message: str,
        trace_id: str,
        stream_mgr: StreamManager,
        user_id: str,
        session_id: str,
        start_time: float,
    ) -> dict:
        """Use the persisted contact-request result as the only source of truth."""
        results = await self._dispatch_tools(
            ["contact"],
            message,
            trace_id,
            stream_mgr,
            user_id=user_id,
            session_id=session_id,
        )
        result = results[0] if results else None
        response_text = (
            getattr(result, "display_text", "")
            or "这次没有成功发出联系请求，请直接联系身边可信任的人。"
        )
        status = getattr(result, "status", "failed")
        data = getattr(result, "data", None) or {}
        tool_entry: dict = {"tool": "contact", "status": status}
        if action := data.get("action"):
            tool_entry["action"] = action

        ttft_ms = int((time.monotonic() - start_time) * 1000)
        await stream_mgr.send_first_reply(response_text, ttft_ms)
        total_latency_ms = int((time.monotonic() - start_time) * 1000)
        message_id = str(uuid.uuid4())
        await stream_mgr.send_final(
            trace_id=trace_id,
            message_id=message_id,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tools_used=[tool_entry],
            memory_updated=False,
        )
        evidence_status = await self._persist_conversation(
            session_id, user_id, message, response_text,
            trace_id=trace_id, assistant_message_id=message_id,
        )
        return {
            "trace_id": trace_id,
            "message_id": message_id,
            "ttft_ms": ttft_ms,
            "total_latency_ms": total_latency_ms,
            "deterministic_contact": True,
            "message_evidence": evidence_status,
        }

    async def _run_deterministic_capability(
        self,
        *,
        message: str,
        trace_id: str,
        stream_mgr: StreamManager,
        user_id: str,
        session_id: str,
        start_time: float,
    ) -> dict:
        from app.runtime.capability_response import ELDER_CAPABILITY_RESPONSE

        response_text = ELDER_CAPABILITY_RESPONSE
        ttft_ms = int((time.monotonic() - start_time) * 1000)
        await stream_mgr.send_first_reply(response_text, ttft_ms)
        total_latency_ms = int((time.monotonic() - start_time) * 1000)
        message_id = str(uuid.uuid4())
        await stream_mgr.send_final(
            trace_id=trace_id,
            message_id=message_id,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tools_used=[],
            memory_updated=False,
        )
        evidence_status = await self._persist_conversation(
            session_id,
            user_id,
            message,
            response_text,
            trace_id=trace_id,
            assistant_message_id=message_id,
        )
        await _trace_svc.add_event(
            trace_id=trace_id,
            step_name="capability_response_final",
            step_index=10,
            user_id=_stable_uuid(user_id),
            session_id=_stable_uuid(session_id),
            output_json={"message_id": message_id, "response_kind": "elder_capabilities"},
            status="success",
            latency_ms=total_latency_ms,
        )
        return {
            "trace_id": trace_id,
            "message_id": message_id,
            "ttft_ms": ttft_ms,
            "total_latency_ms": total_latency_ms,
            "deterministic_capability": True,
            "message_evidence": evidence_status,
        }

    async def _run_analyzers(self, input: AnalyzerInput) -> tuple:
        """Run all analyzers in parallel with individual timeouts."""
        timeout_ms = self._timeout("analyzer")

        async def _safe_analyze(engine_name: str, default):
            try:
                engine = self._get_engine(engine_name)
                if engine:
                    return await asyncio.wait_for(
                        engine.analyze(input),
                        timeout=timeout_ms / 1000,
                    )
            except asyncio.TimeoutError:
                logger.warning(f"{engine_name} timed out ({timeout_ms}ms)")
            except Exception as exc:
                logger.warning(
                    "Analyzer failed engine=%s error_class=%s code=analyzer_failed",
                    engine_name,
                    type(exc).__name__,
                )
            if engine_name == "risk":
                return RiskResult(
                    level="critical",
                    category="safety_unavailable",
                    confidence=1.0,
                    triggered_rules=["risk_engine_unavailable"],
                )
            return default

        intent, emotion, risk, memory = await asyncio.gather(
            _safe_analyze("intent", IntentResult(primary_intent="chitchat", confidence=0.5)),
            _safe_analyze("emotion", EmotionResult()),
            _safe_analyze("risk", RiskResult()),
            self._safe_memory_load(input),
        )
        return intent, emotion, risk, memory

    async def _safe_memory_load(self, input: AnalyzerInput) -> MemorySnapshot:
        """Load memory with separate timeout."""
        timeout_ms = self._timeout("memory_recall")
        try:
            engine = self._get_engine("memory")
            if engine:
                return await asyncio.wait_for(
                    engine.analyze(input),
                    timeout=timeout_ms / 1000,
                )
        except asyncio.TimeoutError:
            logger.warning(f"Memory recall timed out ({timeout_ms}ms)")
        except Exception as exc:
            logger.warning(
                "Memory recall failed error_class=%s code=memory_recall_failed",
                type(exc).__name__,
            )
        return MemorySnapshot()

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
        user_message: str | None = None,
    ):
        """Handle high/critical risk: send alert and safe response."""
        from app.runtime.risk_gate import load_safety_message, notification_notice

        summary = self._build_family_notification_summary(risk)
        base_message = load_safety_message(risk.level, risk.category)
        await stream_mgr.send_risk_alert(risk.level, "")
        ttft_ms = int((time.monotonic() - start_time) * 1000)
        await stream_mgr.send_first_reply(base_message, ttft_ms)

        try:
            notify_status = await asyncio.wait_for(
                self._dispatch_risk_notification(
                    user_id,
                    risk.level,
                    risk.category,
                    summary,
                    trace_id,
                ),
                timeout=_RISK_NOTIFICATION_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Notification dispatch timed out trace=%s code=notification_dispatch_timeout",
                trace_id[:80],
            )
            notify_status = {
                "status": "failed",
                "records": 0,
                "webhook_status": None,
                "error_class": "TimeoutError",
                "error_code": "notification_dispatch_timeout",
            }
        except Exception as exc:
            logger.error(
                "Notification dispatch failed trace=%s error_class=%s code=notification_dispatch_failed",
                trace_id[:80], type(exc).__name__,
            )
            notify_status = {
                "status": "failed",
                "records": 0,
                "webhook_status": None,
                "error_class": type(exc).__name__,
                "error_code": "notification_dispatch_failed",
            }
        notice = notification_notice(notify_status)
        await stream_mgr.send_delta(f" {notice}")
        response_text = f"{base_message.rstrip()} {notice}"
        message_id = str(uuid.uuid4())

        async def persist_risk_audit() -> None:
            from app.observability.message_evidence import persist_turn_messages

            if not session_id:
                raise LookupError("risk turn has no session")
            persisted = await persist_turn_messages(
                session_id=session_id,
                user_id=user_id,
                trace_id=trace_id,
                user_content=user_message or "[risk input unavailable]",
                assistant_content=response_text,
                assistant_message_id=message_id,
            )
            if persisted.assistant_message_id != message_id:
                raise RuntimeError("assistant message ID mismatch")
            await _trace_svc.add_event(
                trace_id=trace_id,
                step_name="family_notification",
                step_index=5,
                user_id=_stable_uuid(user_id),
                output_json={
                    key: notify_status[key]
                    for key in (
                        "status", "records", "webhook_status", "delivery_status",
                        "error_class", "error_code",
                    )
                    if key in notify_status
                },
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
                    "total_latency_ms": int((time.monotonic() - start_time) * 1000),
                    "notification_status": notify_status.get("status"),
                },
                status="success",
                latency_ms=int((time.monotonic() - start_time) * 1000),
                required=True,
            )

        trace_status = "persisted"
        try:
            await asyncio.wait_for(
                persist_risk_audit(),
                timeout=_RISK_TRACE_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            trace_status = "failed"
            logger.error(
                "Risk trace persistence timed out trace=%s code=risk_trace_timeout",
                trace_id[:80],
            )
        except Exception as exc:
            trace_status = "failed"
            logger.error(
                "Risk trace persistence failed trace=%s error_class=%s code=risk_trace_failed",
                trace_id[:80], type(exc).__name__,
            )
        finally:
            if analysis_trace is not None:
                if not analysis_trace.done():
                    analysis_trace.cancel()
                await asyncio.gather(analysis_trace, return_exceptions=True)
        total_latency_ms = int((time.monotonic() - start_time) * 1000)
        await stream_mgr.send_final(
            trace_id=trace_id,
            message_id=message_id,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tools_used=[],
            memory_updated=False,
        )
        return {
            "message_id": message_id,
            "notification_status": {
                key: notify_status[key]
                for key in (
                    "status", "webhook_status", "delivery_status",
                    "error_class", "error_code",
                )
                if key in notify_status
            },
            "risk_trace_persistence": trace_status,
        }

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
            logger.error(
                "Notification dispatch failed trace=%s error_class=%s code=notification_dispatch_failed",
                trace_id[:80], type(exc).__name__,
            )
            return {
                "status": "failed",
                "records": 0,
                "webhook_status": None,
                "error_class": type(exc).__name__,
                "error_code": "notification_dispatch_failed",
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
        """Use dedicated fast model for a quick first reply. Returns True if sent.

        Uses the "fast" role model (a cheaper/faster model) instead of primary,
        so we don't double-bill the same expensive model.
        Skips entirely if no fast model is configured.
        """
        timeout_ms = self._timeout("fast_reply")

        try:
            from app.models.router import model_router

            try:
                model = await model_router.get_model("fast")
            except Exception:
                logger.debug("No fast model configured, skipping fast reply")
                return False

            fast_prompt = [
                {"role": "system", "content": f"你是一个{personality.tone}的 AI Companion。用户当前情绪：{emotion.emotion}(强度{emotion.intensity})。请用一句自然的话回应用户，不超过{personality.max_length or 80}字。"},
                {"role": "user", "content": message},
            ]

            first_token = None
            try:
                async def get_first_token():
                    async for token in model.stream_chat(fast_prompt):
                        return token
                    return None

                first_token = await asyncio.wait_for(
                    get_first_token(),
                    timeout=timeout_ms / 1000,
                )
            except asyncio.TimeoutError:
                logger.debug("Fast reply timed out after %sms", timeout_ms)

            if first_token and not cancel_event.is_set():
                ttft_ms = int((time.monotonic() - start_time) * 1000)
                await stream_mgr.send_first_reply(first_token, ttft_ms)
                return True

        except Exception as exc:
            logger.warning(
                "Fast reply race failed error_class=%s code=fast_reply_failed",
                type(exc).__name__,
            )

        return False

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
        """Get personality config using cached engine."""
        engine = _get_cached_engine("personality")
        if engine is None:
            try:
                from app.engines.personality_engine import PersonalityEngine
                _engine_cache["personality"] = PersonalityEngine()
                engine = _engine_cache["personality"]
            except ImportError:
                return PersonalityConfig()
        return await engine.adapt(emotion=emotion, intent=intent)

    async def _persist_conversation(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        ai_response: str,
        *,
        trace_id: str | None = None,
        assistant_message_id: str | None = None,
    ):
        """Write reconstructable PostgreSQL evidence, then update L0 memory."""
        evidence_status = "not_attempted"
        if trace_id and assistant_message_id and ai_response:
            try:
                from app.observability.message_evidence import persist_turn_messages

                persisted = await persist_turn_messages(
                    session_id=session_id,
                    user_id=user_id,
                    trace_id=trace_id,
                    user_content=user_message,
                    assistant_content=ai_response,
                    assistant_message_id=assistant_message_id,
                )
                if persisted.assistant_message_id != assistant_message_id:
                    raise RuntimeError("assistant message ID mismatch")
                evidence_status = "persisted"
            except Exception as exc:
                evidence_status = "failed"
                logger.error(
                    "Harness message evidence failed trace=%s error_class=%s code=message_evidence_failed",
                    trace_id[:80],
                    type(exc).__name__,
                )
        try:
            from app.storage.working_memory import append_message
            await append_message(session_id, "user", user_message)
            if ai_response:
                await append_message(session_id, "assistant", ai_response)
        except Exception as exc:
            logger.warning(
                "Working memory persistence failed error_class=%s code=working_memory_persist_failed",
                type(exc).__name__,
            )

        from app.config.settings import settings
        if not settings.enable_celery_tasks:
            return evidence_status

        try:
            from app.workers.memory_worker import (
                evaluate_importance, update_session_summary,
            )
            evaluate_importance.delay(user_id, user_message, session_id)
            if ai_response:
                update_session_summary.delay(session_id)
        except Exception as exc:
            logger.debug("Celery memory tasks skipped: %s", exc)
        return evidence_status

    def _generate_trace_id(self, user_id: str) -> str:
        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d")
        uid_short = user_id[:8] if len(user_id) > 8 else user_id
        return f"trace_{date_str}_{uid_short}_{nanoid(size=8)}"
