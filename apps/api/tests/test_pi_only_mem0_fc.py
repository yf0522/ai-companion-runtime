"""Phase 1–5 unit tests: analyzers, FC whitelist, mem0, Gate C deletion guards."""
from __future__ import annotations

import ast
import asyncio
import uuid as uuid_mod
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

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

_REPO_ROOT = Path(__file__).resolve().parents[3]


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


def _fake_session_factory():
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    return FakeSession


@pytest.mark.asyncio
async def test_mem0_empty_does_not_dump_lifecycle(monkeypatch):
    """A3 / I7: mem0 empty search must not dump granted lifecycle rows."""
    from app.memory.adapter import MemoryBusinessAdapter

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

    monkeypatch.setattr("app.db.session.async_session", _fake_session_factory())
    monkeypatch.setattr("app.memory.adapter.select_retrievable_memories", fake_select)

    adapter = MemoryBusinessAdapter(backend=Mem0Backend())
    fragments, meta = await adapter._recall_inner(
        user_id="11111111-1111-1111-1111-111111111111",
        uid=uuid_mod.UUID("11111111-1111-1111-1111-111111111111"),
        query_intent="喜欢什么",
        time_from=None,
        time_to=None,
        limit=5,
    )
    assert fragments == []
    assert meta.get("no_dump") is True
    assert meta.get("reason") == "mem0_empty_no_dump"

    recall = await adapter.recall(
        user_id="11111111-1111-1111-1111-111111111111",
        query_intent="喜欢什么",
    )
    assert recall.status == "empty"
    assert recall.fragments == []
    assert recall.degraded is True
    assert recall.data and recall.data.get("engine") == "mem0"
    assert recall.data.get("no_dump") is True
    assert recall.data.get("reason") == "mem0_empty_no_dump"
    assert "暂时不可用" in recall.display_text
    assert "没有已授权" not in recall.display_text


@pytest.mark.asyncio
async def test_lifecycle_backend_still_dumps_when_empty_engine(monkeypatch):
    from app.memory.adapter import MemoryBusinessAdapter

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

    monkeypatch.setattr("app.db.session.async_session", _fake_session_factory())
    monkeypatch.setattr("app.memory.adapter.select_retrievable_memories", fake_select)

    adapter = MemoryBusinessAdapter(backend=LifeBackend())
    fragments, meta = await adapter._recall_inner(
        user_id="11111111-1111-1111-1111-111111111111",
        uid=uuid_mod.UUID("11111111-1111-1111-1111-111111111111"),
        query_intent="",
        time_from=None,
        time_to=None,
        limit=5,
    )
    assert len(fragments) == 1
    assert fragments[0]["content"] == "我喜欢早起"
    assert meta.get("no_dump") is not True


@pytest.mark.asyncio
async def test_mem0_closed_loop_note_recall_consent(monkeypatch):
    """I4: note → mem0 search hit matched via lifecycle_id + granted consent."""
    from app.memory.adapter import MemoryBusinessAdapter

    lifecycle_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    stored: dict[str, Any] = {}

    class Mem0Backend:
        name = "mem0"

        async def add(self, **kwargs):
            stored["content"] = kwargs["content"]
            stored["metadata"] = dict(kwargs.get("metadata") or {})
            return "mem0-engine-id-1"

        async def search(self, **kwargs):
            return [
                {
                    "id": "mem0-engine-id-1",
                    "content": stored.get("content") or "我怕吵",
                    "score": 0.91,
                    "category": "preference",
                    "metadata": {
                        "lifecycle_id": lifecycle_id,
                        "consent_status": "granted",
                        "category": "preference",
                    },
                }
            ]

    granted_row = {
        "id": lifecycle_id,
        "content": "我怕吵",
        "purpose": "preference",
        "sensitivity": "normal",
        "created_at": None,
    }

    async def fake_select(*args, **kwargs):
        if kwargs.get("purpose") == "preference":
            return [granted_row]
        return []

    async def fake_lifecycle_add(self, **kwargs):
        return lifecycle_id

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr("app.db.session.async_session", _fake_session_factory())
    monkeypatch.setattr("app.memory.adapter.select_retrievable_memories", fake_select)
    monkeypatch.setattr(
        "app.memory.lifecycle_backend.LifecycleMemoryBackend.add",
        fake_lifecycle_add,
    )
    monkeypatch.setenv("MEM0_ENABLED", "1")

    adapter = MemoryBusinessAdapter(backend=Mem0Backend())
    note = await adapter.note(
        user_id="11111111-1111-1111-1111-111111111111",
        summary="我怕吵",
        category="preference",
        explicit_user_request=True,
    )
    assert note.status == "granted"
    assert note.memory_id == lifecycle_id
    assert note.data and note.data.get("engine") == "mem0"
    assert note.data.get("engine_id") == "mem0-engine-id-1"
    assert note.data.get("consent_status") == "granted"
    assert stored["metadata"].get("lifecycle_id") == lifecycle_id

    recall = await adapter.recall(
        user_id="11111111-1111-1111-1111-111111111111",
        query_intent="怕吵",
    )
    assert recall.status == "success"
    assert recall.data and recall.data.get("engine") == "mem0"
    assert [f["content"] for f in recall.fragments] == ["我怕吵"]
    assert recall.fragments[0]["id"] == lifecycle_id


@pytest.mark.asyncio
async def test_mem0_filters_ungranted_engine_hit(monkeypatch):
    """I4: engine hit without matching granted lifecycle row is filtered out."""
    from app.memory.adapter import MemoryBusinessAdapter

    class Mem0Backend:
        name = "mem0"

        async def search(self, **kwargs):
            return [
                {
                    "id": "orphan-mem0",
                    "content": "未授权内容不应出现",
                    "score": 0.99,
                    "metadata": {"lifecycle_id": "dddddddd-dddd-dddd-dddd-dddddddddddd"},
                }
            ]

        async def add(self, **kwargs):
            return None

    async def fake_select(*args, **kwargs):
        return []

    monkeypatch.setattr("app.db.session.async_session", _fake_session_factory())
    monkeypatch.setattr("app.memory.adapter.select_retrievable_memories", fake_select)

    adapter = MemoryBusinessAdapter(backend=Mem0Backend())
    recall = await adapter.recall(
        user_id="11111111-1111-1111-1111-111111111111",
        query_intent="什么",
    )
    assert recall.status == "empty"
    assert recall.fragments == []
    assert recall.data and recall.data.get("engine") == "mem0"


@pytest.mark.asyncio
async def test_mem0_enabled_unavailable_uses_degraded_not_lifecycle(monkeypatch):
    """MEM0_ENABLED + init fail → DegradedMem0Backend (name=mem0), never lifecycle dump."""
    from app.memory import backend as backend_mod

    monkeypatch.setenv("MEM0_ENABLED", "1")
    monkeypatch.setattr(
        "app.memory.mem0_backend.try_build_mem0_backend",
        lambda: None,
    )
    # Reset any cached imports by calling factory directly.
    be = backend_mod.get_memory_backend()
    assert be.name == "mem0"
    assert getattr(be, "degraded", False) is True
    assert await be.search(user_id="u", query="x") == []

    granted_rows = [
        {
            "id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            "content": "有很多已授权记忆",
            "purpose": "preference",
            "sensitivity": "normal",
            "created_at": None,
        }
    ]

    async def fake_select(*args, **kwargs):
        return list(granted_rows)

    monkeypatch.setattr("app.db.session.async_session", _fake_session_factory())
    monkeypatch.setattr("app.memory.adapter.select_retrievable_memories", fake_select)

    from app.memory.adapter import MemoryBusinessAdapter

    adapter = MemoryBusinessAdapter(backend=be)
    recall = await adapter.recall(
        user_id="11111111-1111-1111-1111-111111111111",
        query_intent="记得什么",
    )
    assert recall.status == "empty"
    assert recall.fragments == []
    assert recall.degraded is True
    assert recall.data and recall.data.get("no_dump") is True
    assert recall.data.get("engine") == "mem0"
    assert "暂时不可用" in recall.display_text
    assert "没有已授权" not in recall.display_text


@pytest.mark.asyncio
async def test_mem0_timeout_degrade_no_dump(monkeypatch):
    """I7: mem0 timeout → empty/degrade; no granted dump into fragments."""
    from app.memory.adapter import MemoryBusinessAdapter

    class SlowMem0:
        name = "mem0"

        async def search(self, **kwargs):
            await asyncio.sleep(1)
            return [{"id": "x", "content": "should not appear"}]

        async def add(self, **kwargs):
            return None

    adapter = MemoryBusinessAdapter(backend=SlowMem0(), recall_timeout_ms=50)
    result = await adapter.recall(
        user_id="11111111-1111-1111-1111-111111111111",
        query_intent="x",
    )
    assert result.status == "timeout"
    assert result.fragments == []
    assert result.degraded is True
    assert result.data and result.data.get("engine") == "mem0"
    assert "暂时不可用" in result.display_text
    assert "没有已授权" not in result.display_text


@pytest.mark.asyncio
async def test_true_no_granted_memories_copy_stays_honest(monkeypatch):
    """When there are no granted rows, copy may say no authorized memories."""
    from app.memory.adapter import MemoryBusinessAdapter

    class Mem0Backend:
        name = "mem0"

        async def search(self, **kwargs):
            return []

        async def add(self, **kwargs):
            return None

    async def fake_select(*args, **kwargs):
        return []

    monkeypatch.setattr("app.db.session.async_session", _fake_session_factory())
    monkeypatch.setattr("app.memory.adapter.select_retrievable_memories", fake_select)

    adapter = MemoryBusinessAdapter(backend=Mem0Backend())
    recall = await adapter.recall(
        user_id="11111111-1111-1111-1111-111111111111",
        query_intent="喜欢什么",
    )
    assert recall.status == "empty"
    assert recall.data and recall.data.get("reason") == "no_granted_memories"
    assert recall.data.get("no_dump") is False
    assert "没有已授权的长期记忆" in recall.display_text


@pytest.mark.asyncio
async def test_mem0_enabled_skips_analyzer_lifecycle_l3(monkeypatch):
    """Dual-path fix: MEM0_ENABLED → analyzer vectors empty; LTM via FC only."""
    from app.engines.base import AnalyzerInput
    from app.engines.memory_engine import MemoryEngine

    engine = MemoryEngine()
    uid = "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf"

    monkeypatch.setenv("MEM0_ENABLED", "1")
    monkeypatch.setattr(
        "app.storage.working_memory.get_working_memory",
        AsyncMock(return_value=[{"role": "user", "content": "hi"}]),
        raising=False,
    )
    monkeypatch.setattr(
        "app.storage.working_memory.get_session_summary",
        AsyncMock(return_value="summary"),
        raising=False,
    )
    monkeypatch.setattr(
        engine,
        "_load_profile",
        AsyncMock(return_value={"name": "张三"}),
    )
    load_l3 = AsyncMock(
        return_value=[{"content": "ghost lifecycle memory", "score": 0.9, "id": "m1"}]
    )
    monkeypatch.setattr(engine, "_load_important_memories", load_l3)

    snap = await engine.analyze(
        AnalyzerInput(
            user_id=uid,
            session_id="sess",
            message="记得什么",
            trace_id="tr_dual",
        )
    )
    assert snap.profile["name"] == "张三"
    assert snap.vectors == []
    load_l3.assert_not_awaited()


@pytest.mark.asyncio
async def test_mem0_disabled_still_loads_analyzer_l3(monkeypatch):
    from app.engines.base import AnalyzerInput
    from app.engines.memory_engine import MemoryEngine

    engine = MemoryEngine()
    monkeypatch.delenv("MEM0_ENABLED", raising=False)
    monkeypatch.setattr(
        "app.storage.working_memory.get_working_memory",
        AsyncMock(return_value=[]),
        raising=False,
    )
    monkeypatch.setattr(
        "app.storage.working_memory.get_session_summary",
        AsyncMock(return_value=None),
        raising=False,
    )
    monkeypatch.setattr(engine, "_load_profile", AsyncMock(return_value={}))
    monkeypatch.setattr(
        engine,
        "_load_important_memories",
        AsyncMock(return_value=[{"content": "lifecycle ok", "score": 0.8, "id": "m2"}]),
    )

    # Ensure settings.mem0_enabled does not keep the path on.
    monkeypatch.setattr("app.memory.backend.mem0_enabled", lambda: False)

    snap = await engine.analyze(
        AnalyzerInput(
            user_id="4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
            session_id="sess",
            message="hi",
            trace_id="tr_l3",
        )
    )
    assert len(snap.vectors) == 1
    assert snap.vectors[0]["content"] == "lifecycle ok"


@pytest.mark.asyncio
async def test_execute_tool_rejects_unknown_name():
    from app.tools.registry import execute_tool

    result = await execute_tool("shell_exec", {"cmd": "id"})
    assert result.status == "failed"
    assert result.data and result.data.get("reason") == "unknown_tool"
    assert "未知工具" in result.display_text


# --- Gate C / Phase 5 deletion + infra guards ---


def test_harness_shell_modules_physically_deleted():
    """S10: AgentHarness shell must be gone; analyzers remain importable."""
    import importlib.util

    assert importlib.util.find_spec("app.runtime.agent_harness") is None
    assert importlib.util.find_spec("app.runtime.harness_runtime") is None
    assert importlib.util.find_spec("app.runtime.analyzers") is not None
    harness_py = _REPO_ROOT / "apps/api/app/runtime/agent_harness.py"
    assert not harness_py.exists()


def test_pi_runtime_source_does_not_dispatch_tool_needs():
    """U5 / A4: TOOL_RULES / intent.tool_needs must not drive Pi tool dispatch."""
    src = (_REPO_ROOT / "apps/api/app/runtime/pi_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "tool_needs":
            pytest.fail("pi_runtime must not read intent.tool_needs as a tool router")
    assert "TOOL_RULES" not in src


def test_compose_defines_pi_sidecar_with_healthcheck():
    """U8 / A5: compose includes pi-sidecar + healthcheck; no harness fallback."""
    compose_path = _REPO_ROOT / "infra/docker-compose.yml"
    data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = data["services"]
    assert "pi-sidecar" in services
    assert "healthcheck" in services["pi-sidecar"]
    api_env = "\n".join(str(x) for x in services["api"].get("environment") or [])
    assert "PI_SIDECAR_URL" in api_env
    assert "ENABLE_PI_RUNTIME=1" in api_env
    full = compose_path.read_text(encoding="utf-8")
    assert "harness_fallback" not in full
    assert "AgentHarness" not in full


def test_runtime_yaml_timeouts_present():
    """Timeout budgets live in runtime.yaml after harness.yaml deletion."""
    path = _REPO_ROOT / "apps/api/app/config/runtime.yaml"
    assert path.is_file()
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))["runtime"]
    assert cfg["timeouts"]["fast_reply"] == 300
    assert cfg["timeouts"]["analyzer"] == 100
    assert not (_REPO_ROOT / "apps/api/app/config/harness.yaml").exists()
