"""Phase 1–2 unit tests: analyzers, utility whitelist, mem0 no-dump."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engines.base import EmotionResult, IntentResult, PersonalityConfig
from app.runtime.analyzers import (
    FAST_REPLY_BUDGET_MS,
    build_personality_system_prompt,
    enqueue_post_process,
    fast_reply_race,
    run_analyzer_chain,
)
from app.tools.registry import (
    FC_WHITELIST,
    build_default_tools,
    list_tool_schemas,
    normalize_tool_request,
)
from app.tools.utility_tool import UtilityTool


def test_registry_whitelist_exactly_three():
    from app.tools import registry as reg_mod

    reg_mod._TOOLS = None
    names = {s["name"] for s in list_tool_schemas()}
    assert names == FC_WHITELIST == {"caretask", "memory", "utility"}
    reg = build_default_tools()
    assert set(reg.keys()) == {"caretask", "memory", "utility"}
    assert "weather" not in reg
    assert "reminder" not in reg
    assert "calculator" not in reg
    assert "search" not in reg


def test_legacy_tool_names_map_to_whitelist():
    name, params = normalize_tool_request("weather", {"query": "北京天气"})
    assert name == "utility"
    assert params["op"] == "weather"
    name, params = normalize_tool_request("reminder", {"query": "提醒我吃药"})
    assert name == "caretask"
    name, params = normalize_tool_request("calculator", {})
    assert name == "utility" and params["op"] == "calculator"


@pytest.mark.asyncio
async def test_utility_calculator_op():
    tool = UtilityTool()
    result = await tool.execute({"op": "calculator", "query": "12加35等于多少"})
    assert result.tool_name == "utility"
    assert result.status == "success"
    assert result.data and result.data.get("op") == "calculator"
    assert "47" in result.display_text or result.data.get("result") == 47


@pytest.mark.asyncio
async def test_personality_prompt_mentions_utility():
    prompt = build_personality_system_prompt(
        PersonalityConfig(tone="warm"),
        EmotionResult(emotion="fatigue", intensity=0.4),
        IntentResult(primary_intent="task"),
    )
    assert "utility" in prompt
    assert "fatigue" in prompt or "emotion" in prompt.lower() or "User emotion" in prompt


@pytest.mark.asyncio
async def test_run_analyzer_chain_returns_bundle(monkeypatch):
    from app.engines.base import MemorySnapshot

    async def fake_iem(*args, **kwargs):
        return (
            IntentResult(primary_intent="chitchat", confidence=0.6),
            EmotionResult(emotion="neutral"),
            MemorySnapshot(),
        )

    async def fake_personality(*args, **kwargs):
        return PersonalityConfig(tone="calm")

    monkeypatch.setattr("app.runtime.analyzers.run_intent_emotion_memory", fake_iem)
    monkeypatch.setattr("app.runtime.analyzers.get_personality", fake_personality)

    bundle = await run_analyzer_chain(
        user_id="u1",
        session_id="s1",
        message="你好",
        trace_id="t1",
    )
    assert bundle.intent.primary_intent == "chitchat"
    assert bundle.personality.tone == "calm"
    assert bundle.latency_ms >= 0


@pytest.mark.asyncio
async def test_fast_reply_race_budget_constant():
    assert FAST_REPLY_BUDGET_MS == 300


@pytest.mark.asyncio
async def test_fast_reply_race_emits_without_sidecar(monkeypatch):
    class FakeModel:
        async def stream_chat(self, prompt):
            yield "先回一句"

    class FakeRouter:
        async def get_model(self, role):
            assert role == "fast"
            return FakeModel()

    monkeypatch.setattr("app.models.router.model_router", FakeRouter())

    stream = MagicMock()
    stream.send_first_reply = AsyncMock()
    import time

    start = time.monotonic()
    sent, ttft = await fast_reply_race(
        "你好",
        EmotionResult(),
        PersonalityConfig(),
        stream,
        start,
        asyncio.Event(),
        budget_ms=300,
    )
    assert sent is True
    assert ttft is not None
    assert ttft <= 300 + 200
    stream.send_first_reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_post_process_reflection(monkeypatch):
    monkeypatch.setattr(
        "app.storage.working_memory.append_message",
        AsyncMock(),
    )

    from app.config.settings import settings

    monkeypatch.setattr(settings, "enable_celery_tasks", True)

    calls = {"reflection": 0, "memory": 0}

    def fake_eval(*a, **k):
        calls["memory"] += 1

    def fake_sum(*a, **k):
        calls["memory"] += 1

    def fake_reflect(*a, **k):
        calls["reflection"] += 1

    monkeypatch.setattr(
        "app.workers.memory_worker.evaluate_importance",
        MagicMock(delay=fake_eval),
    )
    monkeypatch.setattr(
        "app.workers.memory_worker.update_session_summary",
        MagicMock(delay=fake_sum),
    )
    monkeypatch.setattr(
        "app.workers.reflection_worker.run_reflection",
        MagicMock(delay=fake_reflect),
    )

    meta = await enqueue_post_process(
        user_id="u",
        session_id="s",
        user_message="hi",
        ai_response="hello",
    )
    assert meta["reflection"] is True
    assert meta["memory"] is True
    assert calls["reflection"] == 1


@pytest.mark.asyncio
async def test_mem0_empty_does_not_dump_lifecycle(monkeypatch):
    """A3 / I7: mem0 empty search must not dump granted lifecycle rows."""
    from app.memory.adapter import MemoryBusinessAdapter
    import uuid as uuid_mod

    class Mem0Backend:
        name = "mem0"

        async def search(self, **kwargs):
            return []

        async def add(self, **kwargs):
            return None

    granted_rows = [
        {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "content": "我喜欢听评书",
            "purpose": "preference",
            "sensitivity": "normal",
            "created_at": None,
        }
    ] * 5

    async def fake_select(*args, **kwargs):
        return list(granted_rows)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.db.session.async_session", lambda: FakeSession())
    monkeypatch.setattr("app.memory.adapter.select_retrievable_memories", fake_select)

    adapter = MemoryBusinessAdapter(backend=Mem0Backend())
    fragments = await adapter._recall_inner(
        user_id="11111111-1111-1111-1111-111111111111",
        uid=uuid_mod.UUID("11111111-1111-1111-1111-111111111111"),
        query_intent="喜欢什么",
        time_from=None,
        time_to=None,
        limit=5,
    )
    assert fragments == []


@pytest.mark.asyncio
async def test_lifecycle_backend_still_dumps_when_empty_engine(monkeypatch):
    from app.memory.adapter import MemoryBusinessAdapter
    import uuid as uuid_mod

    class LifeBackend:
        name = "lifecycle"

        async def search(self, **kwargs):
            return []

        async def add(self, **kwargs):
            return None

    granted_rows = [
        {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "content": "我喜欢早起",
            "purpose": "preference",
            "sensitivity": "normal",
            "created_at": None,
        }
    ]

    async def fake_select(*args, **kwargs):
        return list(granted_rows)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.db.session.async_session", lambda: FakeSession())
    monkeypatch.setattr("app.memory.adapter.select_retrievable_memories", fake_select)

    adapter = MemoryBusinessAdapter(backend=LifeBackend())
    fragments = await adapter._recall_inner(
        user_id="11111111-1111-1111-1111-111111111111",
        uid=uuid_mod.UUID("11111111-1111-1111-1111-111111111111"),
        query_intent="",
        time_from=None,
        time_to=None,
        limit=5,
    )
    assert len(fragments) == 1
    assert fragments[0]["content"] == "我喜欢早起"
