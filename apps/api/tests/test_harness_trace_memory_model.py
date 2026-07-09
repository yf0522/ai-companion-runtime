"""Harness Trace: memory_recall event + record_model_call."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engines.base import (
    EmotionResult,
    IntentResult,
    MemorySnapshot,
    PersonalityConfig,
    RiskResult,
)
from app.runtime.agent_harness import AgentHarness


class _FakeModel:
    provider = "test"
    model_name = "test-model"

    async def stream_chat(self, messages):
        yield "你好"

    def count_tokens(self, text: str) -> int:
        return max(1, len(text or ""))


@pytest.mark.asyncio
async def test_process_records_memory_recall_and_model_call(monkeypatch):
    harness = AgentHarness()
    recorded_events: list[dict] = []
    recorded_models: list[dict] = []

    async def fake_add_event(**kwargs):
        recorded_events.append(kwargs)

    async def fake_record_model_call(**kwargs):
        recorded_models.append(kwargs)

    monkeypatch.setattr(
        "app.runtime.agent_harness._trace_svc.add_event",
        fake_add_event,
        raising=True,
    )
    monkeypatch.setattr(
        "app.runtime.agent_harness._trace_svc.record_model_call",
        fake_record_model_call,
        raising=True,
    )

    async def fake_analyzers(_input):
        return (
            IntentResult(primary_intent="chitchat", confidence=0.9),
            EmotionResult(emotion="neutral"),
            RiskResult(level="low", category="none"),
            MemorySnapshot(
                working=[{"role": "user", "content": "hi"}],
                summary="summary",
                profile={"name": "王大爷"},
                vectors=[{"id": "m1"}],
            ),
        )

    monkeypatch.setattr(harness, "_run_analyzers", fake_analyzers)
    monkeypatch.setattr(
        harness,
        "_get_personality",
        AsyncMock(return_value=PersonalityConfig()),
    )
    monkeypatch.setattr(harness, "_fast_reply_race", AsyncMock(return_value=False))
    monkeypatch.setattr(harness, "_persist_conversation", AsyncMock())

    class _Router:
        async def get_model(self, role: str):
            return _FakeModel()

    monkeypatch.setattr("app.models.router.model_router", _Router())

    stream_mgr = MagicMock()
    stream_mgr.dead = False
    stream_mgr.send_trace = AsyncMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_delta = AsyncMock()
    stream_mgr.send_final = AsyncMock()

    cancel_event = asyncio.Event()
    result = await harness.run(
        user_id="4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
        session_id="22222222-2222-2222-2222-222222222222",
        message="今天天气不错",
        stream_mgr=stream_mgr,
        cancel_event=cancel_event,
    )

    # Drain pending create_task callbacks without fixed sleep.
    await asyncio.sleep(0)
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.wait(pending, timeout=1.0)

    assert result.get("blocked_by_risk") is not True
    memory_events = [e for e in recorded_events if e.get("step_name") == "memory_recall"]
    assert len(memory_events) == 1
    assert memory_events[0]["output_json"]["working_count"] == 1
    assert memory_events[0]["output_json"]["vector_count"] == 1
    assert memory_events[0]["output_json"]["has_profile"] is True

    assert len(recorded_models) == 1
    assert recorded_models[0]["provider"] == "test"
    assert recorded_models[0]["model"] == "test-model"
    assert recorded_models[0]["status"] == "success"
