"""L2/L3 memory recall and eldercare importance scoring tests."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.engines.base import AnalyzerInput
from app.engines.memory_engine import MemoryEngine
from app.workers.memory_worker import score_importance


@pytest.mark.asyncio
async def test_analyze_returns_profile_and_memories(monkeypatch):
    engine = MemoryEngine()
    user_id = uuid.UUID("4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf")

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
        AsyncMock(return_value={"meds": ["降压药"], "name": "张三"}),
    )
    monkeypatch.setattr(
        engine,
        "_load_important_memories",
        AsyncMock(
            return_value=[
                {
                    "content": "每天吃降压药",
                    "score": 0.9,
                    "memory_type": "fact",
                    "id": "m1",
                }
            ]
        ),
    )

    snap = await engine.analyze(
        AnalyzerInput(
            user_id=str(user_id),
            session_id="sess",
            message="今天怎么样",
            trace_id="tr_mem",
        )
    )
    assert snap.summary == "summary"
    assert snap.profile["meds"] == ["降压药"]
    assert snap.vectors[0]["content"] == "每天吃降压药"


@pytest.mark.asyncio
async def test_analyze_degrades_when_db_fails(monkeypatch):
    engine = MemoryEngine()
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

    class _BoomSession:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            return None

    session_module = __import__("app.db.session", fromlist=["async_session"])
    monkeypatch.setattr(session_module, "async_session", lambda: _BoomSession())

    snap = await engine.analyze(
        AnalyzerInput(
            user_id="4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
            session_id="sess",
            message="hi",
            trace_id="tr_fail",
        )
    )
    assert snap.profile == {}
    assert snap.vectors == []


def test_eldercare_keywords_score_above_threshold():
    assert score_importance("我每天吃降压药") >= 0.6
    assert score_importance("明天去医院复诊") >= 0.6
    assert score_importance("有人打电话要验证码像诈骗") >= 0.6
    assert score_importance("今天天气不错") < 0.6


@pytest.mark.asyncio
async def test_load_profile_and_memories_from_fake_db(monkeypatch):
    engine = MemoryEngine()
    uid = uuid.UUID("4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf")

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

        def scalars(self):
            return self

        def all(self):
            return self._value if isinstance(self._value, list) else []

    class _ProfileSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def execute(self, stmt):
            return _Result(SimpleNamespace(profile_json={"city": "上海"}))

    class _MemorySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def execute(self, stmt):
            return _Result(
                [
                    SimpleNamespace(
                        content="吃二甲双胍",
                        importance_score=0.85,
                        memory_type="fact",
                        id=uuid.uuid4(),
                    )
                ]
            )

    session_module = __import__("app.db.session", fromlist=["async_session"])
    monkeypatch.setattr(session_module, "async_session", lambda: _ProfileSession())
    profile = await engine._load_profile(uid)
    monkeypatch.setattr(session_module, "async_session", lambda: _MemorySession())
    vectors = await engine._load_important_memories(uid)
    assert profile == {"city": "上海"}
    assert vectors[0]["content"] == "吃二甲双胍"
    assert vectors[0]["score"] == 0.85
