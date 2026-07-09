from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

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


_harness_config: dict | None = None


def _load_harness_config() -> dict:
    global _harness_config
    if _harness_config is not None:
        return _harness_config
    path = Path(__file__).parent.parent / "config" / "harness.yaml"
    try:
        with open(path) as f:
            _harness_config = yaml.safe_load(f).get("harness", {})
    except Exception as e:
        logger.warning(f"Failed to load harness.yaml: {e}, using defaults")
        _harness_config = {}
    return _harness_config


# Cached engine singletons
_engine_cache: dict[str, object] = {}


def _get_cached_engine(name: str):
    """Return a cached engine instance, creating on first call."""
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

    def _fallback_strategy(self, key: str) -> str:
        return self._config.get("fallback", {}).get(key, "")

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
        import uuid as _uuid
        # Convert string user_id to a deterministic UUID for DB storage
        try:
            db_user_id = str(_uuid.UUID(user_id))
        except (ValueError, AttributeError):
            db_user_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, user_id))
        try:
            db_session_id = str(_uuid.UUID(session_id))
        except (ValueError, AttributeError):
            db_session_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, session_id))

        start_time = time.monotonic()
        trace_id = self._generate_trace_id(user_id)
        step = 0

        # Step 0: Send trace_id
        await stream_mgr.send_trace(trace_id)

        # Step 1: Parallel Analyzer
        step += 1
        analyzer_input = AnalyzerInput(
            user_id=user_id, session_id=session_id,
            message=message, trace_id=trace_id,
        )
        intent, emotion, risk, memory = await self._run_analyzers(analyzer_input)

        # Record analyzer results
        analyzer_ms = int((time.monotonic() - start_time) * 1000)
        asyncio.create_task(_trace_svc.add_event(
            trace_id=trace_id, step_name="intent_detection", step_index=1,
            user_id=db_user_id, session_id=db_session_id,
            output_json=intent.model_dump(), status="success", latency_ms=analyzer_ms,
        ))
        asyncio.create_task(_trace_svc.add_event(
            trace_id=trace_id, step_name="emotion_detection", step_index=2,
            user_id=db_user_id, session_id=db_session_id,
            output_json=emotion.model_dump(), status="success", latency_ms=analyzer_ms,
        ))
        asyncio.create_task(_trace_svc.add_event(
            trace_id=trace_id, step_name="risk_detection", step_index=3,
            user_id=db_user_id, session_id=db_session_id,
            output_json=risk.model_dump(), status="success", latency_ms=analyzer_ms,
        ))
        asyncio.create_task(_trace_svc.add_event(
            trace_id=trace_id, step_name="memory_recall", step_index=4,
            user_id=db_user_id, session_id=db_session_id,
            output_json={
                "working_count": len(memory.working or []),
                "vector_count": len(memory.vectors or []),
                "has_summary": bool(memory.summary),
                "has_profile": bool(memory.profile),
                "profile_keys": list((memory.profile or {}).keys())[:12],
            },
            status="success",
            latency_ms=analyzer_ms,
        ))

        # Step 2: Risk check
        step += 1
        if risk.level in ("critical", "high"):
            await self._handle_risk(risk, stream_mgr, trace_id, start_time, user_id)
            return {"trace_id": trace_id, "blocked_by_risk": True}

        if risk.level == "medium":
            await self._dispatch_risk_notification(
                user_id,
                "medium",
                risk.category,
                self._build_family_notification_summary(risk),
                trace_id,
            )

        # Step 3: Personality + Fast Reply (non-blocking, first-sentence-first)
        step += 1
        personality = await self._get_personality(emotion, intent)

        # Fast reply first — does NOT wait for tools
        fast_reply_sent = await self._fast_reply_race(
            message, emotion, personality, stream_mgr, start_time, cancel_event,
        )

        if cancel_event.is_set():
            return {"trace_id": trace_id, "cancelled": True}

        # Step 4: Main model stream + tool dispatch in parallel
        # Tools run concurrently with the main model.
        # Tool results are sent to the client via tool_result messages.
        # The main model prompt does NOT wait for tools (preserving TTFT).
        step += 1
        ttft_ms = None
        response_text = ""
        tool_results = []
        message_id = f"m_{nanoid(size=12)}"

        # Build prompt (without tool results — they arrive via side-channel)
        from app.runtime.prompt_builder import PromptBuilder
        prompt_builder = PromptBuilder()
        messages = prompt_builder.build(
            user_message=message,
            intent=intent,
            emotion=emotion,
            personality=personality,
            memory=memory,
        )

        # Launch tool dispatch as a background task (non-blocking)
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

        # Stream main model with retry + total timeout
        model_total_timeout = self._timeout("model_total") / 1000  # seconds
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
            except Exception as e:
                retries += 1
                logger.warning(f"Model attempt {retries} failed: {e}")
                if retries > self.max_retries:
                    break

        # Model completely failed
        if not model_success:
            fallback_text = self._template("model_all_fail") or "抱歉，我现在有点反应不过来，你能稍后再试一下吗？"
            if not fast_reply_sent:
                ttft_ms = int((time.monotonic() - start_time) * 1000)
                await stream_mgr.send_first_reply(fallback_text, ttft_ms)
            else:
                await stream_mgr.send_delta(fallback_text)
            response_text = fallback_text

        # Collect tool results (if any) — they've been streaming via tool_result already
        if tool_task:
            try:
                tool_results = await asyncio.wait_for(tool_task, timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning("Tool dispatch did not finish in time after model stream")
                tool_results = []
            except Exception as e:
                logger.warning(f"Tool dispatch failed: {e}")
                tool_results = []

        # Step 5: Final
        total_latency_ms = int((time.monotonic() - start_time) * 1000)
        tools_used = []
        for t in tool_results or []:
            if isinstance(t, dict):
                tools_used.append(t.get("tool_name", ""))
            elif hasattr(t, "tool_name"):
                tools_used.append(t.tool_name)

        prompt_tokens = 0
        output_tokens = 0
        if last_model is not None and hasattr(last_model, "count_tokens"):
            try:
                prompt_tokens = sum(
                    int(last_model.count_tokens(m.get("content", "") or ""))
                    for m in messages
                )
                output_tokens = int(last_model.count_tokens(response_text or ""))
            except Exception as e:
                logger.debug(f"Token counting skipped: {e}")

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

        # Record model stream event
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

        # Record final
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

        # Persist conversation to L0 working memory
        await self._persist_conversation(
            session_id, user_id, message, response_text,
        )

        return {
            "trace_id": trace_id,
            "message_id": message_id,
            "ttft_ms": ttft_ms,
            "total_latency_ms": total_latency_ms,
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
            except Exception as e:
                logger.warning(f"{engine_name} failed: {e}")
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
        except Exception as e:
            logger.warning(f"Memory recall failed: {e}")
        return MemorySnapshot()

    def _get_engine(self, name: str):
        """Get a cached engine singleton. Returns None if not implemented."""
        return _get_cached_engine(name)

    async def _handle_risk(
        self,
        risk: RiskResult,
        stream_mgr: StreamManager,
        trace_id: str,
        start_time: float,
        user_id: str,
    ):
        """Handle high/critical risk: send alert and safe response."""
        await stream_mgr.send_risk_alert(risk.level, "")

        # Load safety messages from risk_rules.yaml
        try:
            path = Path(__file__).parent.parent / "config" / "risk_rules.yaml"
            with open(path) as f:
                rules = yaml.safe_load(f)
            safety_msg = rules.get("safety_messages", {}).get(risk.level, "")
        except Exception as e:
            logger.error(f"Failed to load safety messages from risk_rules.yaml: {e}")
            safety_msg = "如果你正在经历困难，请拨打心理援助热线：400-161-9995"

        ttft_ms = int((time.monotonic() - start_time) * 1000)
        await stream_mgr.send_first_reply(safety_msg, ttft_ms)

        total_latency_ms = int((time.monotonic() - start_time) * 1000)
        await stream_mgr.send_final(
            trace_id=trace_id,
            message_id=f"m_{nanoid(size=12)}",
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tools_used=[],
            memory_updated=False,
        )

        import uuid as _uuid

        summary = self._build_family_notification_summary(risk)
        notify_status = await self._dispatch_risk_notification(
            user_id,
            risk.level,
            risk.category,
            summary,
            trace_id,
        )
        try:
            db_user_id = str(_uuid.UUID(user_id))
        except (ValueError, AttributeError):
            db_user_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, user_id))
        await _trace_svc.add_event(
            trace_id=trace_id,
            step_name="family_notification",
            step_index=4,
            user_id=db_user_id,
            output_json=notify_status,
            status=(
                "success"
                if notify_status.get("status") in {"persisted", "queued"}
                else "failed"
            ),
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
            import uuid as _uuid_mod

            try:
                normalized_user_id = str(_uuid_mod.UUID(user_id))
            except (ValueError, AttributeError):
                normalized_user_id = str(
                    _uuid_mod.uuid5(_uuid_mod.NAMESPACE_DNS, user_id)
                )

            if not settings.enable_celery_tasks:
                from app.workers.notification_worker import process_risk_notification

                # Await high/critical (and any explicit dispatch) so demos cannot
                # silently claim success when persistence failed.
                return await process_risk_notification(
                    normalized_user_id,
                    risk_level,
                    risk_category or "",
                    summary,
                    trace_id,
                )

            from app.workers.notification_worker import send_risk_notification

            send_risk_notification.delay(
                normalized_user_id,
                risk_level,
                risk_category or "",
                summary,
                trace_id,
            )
            return {
                "status": "queued",
                "records": 0,
                "webhook_status": None,
                "error": None,
            }
        except Exception as e:
            logger.error(f"Notification dispatch failed: {e}")
            return {
                "status": "failed",
                "records": 0,
                "webhook_status": None,
                "error": str(e),
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

            # Try to get a dedicated fast model — skip if not configured
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
                pass

            if first_token and not cancel_event.is_set():
                ttft_ms = int((time.monotonic() - start_time) * 1000)
                await stream_mgr.send_first_reply(first_token, ttft_ms)
                return True

        except Exception as e:
            logger.warning(f"Fast reply race failed: {e}")

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
            logger.debug("ToolDispatcher not implemented yet (Phase 3)")
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
        self, session_id: str, user_id: str, user_message: str, ai_response: str,
    ):
        """Write user message and AI response to L0 working memory."""
        try:
            from app.storage.working_memory import append_message
            await append_message(session_id, "user", user_message)
            if ai_response:
                await append_message(session_id, "assistant", ai_response)
        except Exception as e:
            logger.warning(f"Failed to persist conversation to L0: {e}")

        # Fire-and-forget Celery tasks for importance evaluation and summary
        from app.config.settings import settings
        if not settings.enable_celery_tasks:
            return

        try:
            from app.workers.memory_worker import (
                evaluate_importance, update_session_summary,
            )
            evaluate_importance.delay(user_id, user_message, session_id)
            if ai_response:
                update_session_summary.delay(session_id)
        except Exception as e:
            logger.debug(f"Celery memory tasks skipped: {e}")

    def _generate_trace_id(self, user_id: str) -> str:
        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d")
        uid_short = user_id[:8] if len(user_id) > 8 else user_id
        return f"trace_{date_str}_{uid_short}_{nanoid(size=8)}"
