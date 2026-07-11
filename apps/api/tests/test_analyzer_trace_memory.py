"""Pi analyzer Trace: memory_recall event parity (Gate C / U6)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.engines.base import (
    EmotionResult,
    IntentResult,
    MemorySnapshot,
    PersonalityConfig,
    RiskResult,
)
from app.runtime.analyzers import record_analyzer_events


@pytest.mark.asyncio
async def test_record_analyzer_events_includes_memory_recall(monkeypatch):
    recorded_events: list[dict] = []

    async def fake_add_event(**kwargs):
        recorded_events.append(kwargs)

    monkeypatch.setattr(
        "app.runtime.analyzers._trace_svc.add_event",
        fake_add_event,
        raising=True,
    )

    await record_analyzer_events(
        trace_id="tr_mem",
        user_id="4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
        session_id="22222222-2222-2222-2222-222222222222",
        intent=IntentResult(primary_intent="chitchat", confidence=0.9),
        emotion=EmotionResult(emotion="neutral"),
        personality=PersonalityConfig(),
        latency_ms=12,
        risk=RiskResult(level="low", category="none"),
        memory=MemorySnapshot(
            working=[{"role": "user", "content": "hi"}],
            summary="summary",
            profile={"name": "王大爷"},
            vectors=[{"id": "m1"}],
        ),
    )

    memory_events = [e for e in recorded_events if e.get("step_name") == "memory_recall"]
    assert len(memory_events) == 1
    assert memory_events[0]["output_json"]["working_count"] == 1
    assert memory_events[0]["output_json"]["vector_count"] == 1
    assert memory_events[0]["output_json"]["has_profile"] is True

    names = {e["step_name"] for e in recorded_events}
    assert {"intent_detection", "emotion_detection", "personality_adapt", "risk_detection", "memory_recall"} <= names
