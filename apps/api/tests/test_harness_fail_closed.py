from __future__ import annotations

import asyncio
import uuid
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from app.engines.base import EmotionResult, IntentResult, MemorySnapshot, RiskResult
from app.runtime.agent_harness import AgentHarness
from app.runtime.capability_response import ELDER_CAPABILITY_RESPONSE, capability_response_for
from app.tools.base import ToolResult


def _stream() -> MagicMock:
    stream = MagicMock(dead=False)
    for name in (
        "send_trace", "send_tool_status", "send_tool_result", "send_first_reply",
        "send_final", "send_risk_alert", "send_delta",
    ):
        setattr(stream, name, AsyncMock())
    return stream


@pytest.mark.parametrize(
    "message",
    [
        "What tools do you have?",
        "What are your capabilities?",
        "What 功能 do you have?",
    ],
)
def test_python_capability_matcher_covers_pi_english_and_mixed_forms(message):
    response = capability_response_for(message)
    assert response == ELDER_CAPABILITY_RESPONSE
    assert all(word not in response for word in ("CareTask", "Memory", "Contact", "tool"))


@pytest.mark.asyncio
async def test_harness_compound_caretask_uses_internal_batch_executor(monkeypatch):
    harness = AgentHarness()
    monkeypatch.setattr(
        harness,
        "_run_analyzers",
        AsyncMock(return_value=(
            IntentResult(primary_intent="chitchat", confidence=0.5, tool_needs=[]),
            EmotionResult(),
            RiskResult(level="low"),
            MemorySnapshot(),
        )),
    )
    monkeypatch.setattr(harness, "_persist_conversation", AsyncMock(return_value="persisted"))
    monkeypatch.setattr("app.runtime.agent_harness._record_analysis_events", AsyncMock())
    monkeypatch.setattr("app.observability.trace_service.TraceService.record_tool_call", AsyncMock())
    execute = AsyncMock(return_value=ToolResult(
        tool_name="caretask",
        status="success",
        display_text="1. 降压药：已完成\n2. 复诊：已取消",
        data={"action": "caretask_batch", "receipts": []},
    ))
    from app.tools.registry import get_tool_registry

    monkeypatch.setattr(get_tool_registry()["caretask"], "execute", execute)
    stream = _stream()

    result = await harness.run(
        user_id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        message="完成降压药并取消复诊",
        stream_mgr=stream,
        cancel_event=asyncio.Event(),
    )

    params = execute.await_args.args[1] if len(execute.await_args.args) > 1 else execute.await_args.args[0]
    assert params["action"] == "batch"
    assert params["idempotency_key"] == result["trace_id"]
    stream.send_first_reply.assert_awaited_once_with("1. 降压药：已完成\n2. 复诊：已取消", ANY)


@pytest.mark.asyncio
async def test_harness_capability_response_is_risk_first_and_uses_final_message_id(monkeypatch):
    harness = AgentHarness()
    monkeypatch.setattr(
        harness,
        "_run_analyzers",
        AsyncMock(return_value=(
            IntentResult(primary_intent="chitchat", confidence=1.0),
            EmotionResult(),
            RiskResult(level="low"),
            MemorySnapshot(),
        )),
    )
    persist = AsyncMock(return_value="persisted")
    monkeypatch.setattr(harness, "_persist_conversation", persist)
    monkeypatch.setattr("app.runtime.agent_harness._record_analysis_events", AsyncMock())
    monkeypatch.setattr("app.runtime.agent_harness._trace_svc.add_event", AsyncMock())
    stream = _stream()

    result = await harness.run(
        user_id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        message="你都能干些什么",
        stream_mgr=stream,
        cancel_event=asyncio.Event(),
    )

    assert result["deterministic_capability"] is True
    stream.send_first_reply.assert_awaited_once_with(ELDER_CAPABILITY_RESPONSE, ANY)
    final_id = stream.send_final.await_args.kwargs["message_id"]
    assert final_id == result["message_id"]
    assert persist.await_args.kwargs["assistant_message_id"] == final_id
    assert all(word not in ELDER_CAPABILITY_RESPONSE for word in ("CareTask", "Memory", "Contact", "tool"))


@pytest.mark.asyncio
async def test_harness_stalled_model_task_cancellation_cleans_tool_and_emits_no_final(
    monkeypatch,
):
    harness = AgentHarness()
    model_started = asyncio.Event()
    model_cleaned = asyncio.Event()
    tool_cleaned = asyncio.Event()

    class _StalledModel:
        provider = "test"
        model_name = "stalled"

        async def stream_chat(self, _messages):
            model_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                model_cleaned.set()
            if False:
                yield ""

    class _Router:
        async def get_model(self, _role):
            return _StalledModel()

    async def stalled_tool(*_args, **_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            tool_cleaned.set()

    monkeypatch.setattr(
        harness,
        "_run_analyzers",
        AsyncMock(
            return_value=(
                IntentResult(
                    primary_intent="task", confidence=1.0, tool_needs=["calculator"]
                ),
                EmotionResult(),
                RiskResult(level="low"),
                MemorySnapshot(),
            )
        ),
    )
    monkeypatch.setattr(
        harness,
        "_get_personality",
        AsyncMock(
            return_value=MagicMock(
                tone="warm",
                style_rules=[],
                avoid_phrases=[],
                encourage_patterns=[],
                max_length=80,
            )
        ),
    )
    monkeypatch.setattr(harness, "_fast_reply_race", AsyncMock(return_value=False))
    monkeypatch.setattr(harness, "_dispatch_tools", stalled_tool)
    monkeypatch.setattr("app.models.router.model_router", _Router())
    monkeypatch.setattr("app.runtime.agent_harness._record_analysis_events", AsyncMock())
    stream = _stream()

    task = asyncio.create_task(
        harness.run(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            message="算一下",
            stream_mgr=stream,
            cancel_event=asyncio.Event(),
        )
    )
    await asyncio.wait_for(model_started.wait(), timeout=0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.2)

    assert model_cleaned.is_set() is True
    assert tool_cleaned.is_set() is True
    stream.send_first_reply.assert_not_awaited()
    stream.send_final.assert_not_awaited()
