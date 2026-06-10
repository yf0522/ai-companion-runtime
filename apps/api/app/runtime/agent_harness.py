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

logger = logging.getLogger(__name__)


def _load_harness_config() -> dict:
    path = Path(__file__).parent.parent / "config" / "harness.yaml"
    try:
        with open(path) as f:
            return yaml.safe_load(f).get("harness", {})
    except Exception as e:
        logger.warning(f"Failed to load harness.yaml: {e}, using defaults")
        return {}


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

        # Step 2: Risk check
        step += 1
        if risk.level in ("critical", "high"):
            await self._handle_risk(risk, stream_mgr, trace_id, start_time)
            return {"trace_id": trace_id, "blocked_by_risk": True}

        # Step 3: Fast Reply Race
        step += 1
        personality = await self._get_personality(emotion, intent)
        fast_reply_sent = await self._fast_reply_race(
            message, emotion, personality, stream_mgr, start_time, cancel_event,
        )

        if cancel_event.is_set():
            return {"trace_id": trace_id, "cancelled": True}

        # Step 4: Main model stream + tool dispatch
        step += 1
        ttft_ms = None
        response_text = ""
        tool_results = []
        message_id = f"m_{nanoid(size=12)}"

        # Build full prompt
        from app.runtime.prompt_builder import PromptBuilder
        prompt_builder = PromptBuilder()
        messages = prompt_builder.build(
            user_message=message,
            intent=intent,
            emotion=emotion,
            personality=personality,
            memory=memory,
        )

        # Stream main model with retry
        retries = 0
        model_success = False
        while retries <= self.max_retries and not cancel_event.is_set():
            try:
                role = "primary" if retries == 0 else "fallback"
                from app.models.router import model_router
                model = await model_router.get_model(role)
                first_token = True

                async for token in model.stream_chat(messages):
                    if cancel_event.is_set():
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

                model_success = True
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

        # Detect and dispatch tools (async, non-blocking for now)
        if intent.tool_needs and not cancel_event.is_set():
            tool_results = await self._dispatch_tools(
                intent.tool_needs, message, trace_id, stream_mgr,
            )

        # Step 5: Final
        total_latency_ms = int((time.monotonic() - start_time) * 1000)
        tools_used = [t.get("tool_name", "") for t in tool_results if isinstance(t, dict)]

        await stream_mgr.send_final(
            trace_id=trace_id,
            message_id=message_id,
            ttft_ms=ttft_ms or 0,
            total_latency_ms=total_latency_ms,
            tools_used=tools_used,
            memory_updated=False,
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
        """Lazy load engines — returns None if not implemented yet."""
        try:
            if name == "intent":
                from app.engines.intent_engine import IntentEngine
                return IntentEngine()
            elif name == "emotion":
                from app.engines.emotion_engine import EmotionEngine
                return EmotionEngine()
            elif name == "risk":
                from app.engines.risk_engine import RiskEngine
                return RiskEngine()
            elif name == "memory":
                from app.engines.memory_engine import MemoryEngine
                return MemoryEngine()
        except ImportError:
            pass
        return None

    async def _handle_risk(self, risk: RiskResult, stream_mgr: StreamManager, trace_id: str, start_time: float):
        """Handle high/critical risk: send alert and safe response."""
        await stream_mgr.send_risk_alert(risk.level, "")

        # Load safety messages from risk_rules.yaml
        try:
            path = Path(__file__).parent.parent / "config" / "risk_rules.yaml"
            with open(path) as f:
                rules = yaml.safe_load(f)
            safety_msg = rules.get("safety_messages", {}).get(risk.level, "")
        except Exception:
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

    async def _fast_reply_race(
        self, message: str, emotion: EmotionResult, personality: PersonalityConfig,
        stream_mgr: StreamManager, start_time: float, cancel_event: asyncio.Event,
    ) -> bool:
        """Race fast_model vs main_model first token. Returns True if fast reply was sent."""
        timeout_ms = self._timeout("fast_reply")

        try:
            from app.models.router import model_router

            # Try to get first token from main model within timeout
            model = await model_router.get_model("primary")
            fast_prompt = [
                {"role": "system", "content": f"你是一个{personality.tone}的 AI Companion。用户当前情绪：{emotion.emotion}(强度{emotion.intensity})。请用一句自然的话回应用户，不超过{personality.max_length or 80}字。"},
                {"role": "user", "content": message},
            ]

            # Race: wait for first token within fast_reply timeout
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

    async def _dispatch_tools(self, tool_needs: list[str], message: str, trace_id: str, stream_mgr: StreamManager) -> list:
        """Dispatch tools. Returns list of results. Stub for Phase 3."""
        try:
            from app.tools.dispatcher import ToolDispatcher
            dispatcher = ToolDispatcher()
            return await dispatcher.dispatch(tool_needs, message, trace_id, stream_mgr)
        except ImportError:
            logger.debug("ToolDispatcher not implemented yet (Phase 3)")
            return []

    async def _get_personality(self, emotion: EmotionResult, intent=None) -> PersonalityConfig:
        """Get personality config. Stub for Phase 2D."""
        try:
            from app.engines.personality_engine import PersonalityEngine
            engine = PersonalityEngine()
            return await engine.adapt(emotion=emotion, intent=intent)
        except ImportError:
            return PersonalityConfig()

    def _generate_trace_id(self, user_id: str) -> str:
        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d")
        uid_short = user_id[:8] if len(user_id) > 8 else user_id
        return f"trace_{date_str}_{uid_short}_{nanoid(size=8)}"
