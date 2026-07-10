"""Memory tools: refuse rules, consent filter, recall/note actions, care-window list."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.memory.adapter import MemoryBusinessAdapter
from app.memory.lifecycle_backend import LifecycleMemoryBackend
from app.memory.refuse import refuse_memory_note
from app.tools.caretask_service import care_window_bounds, in_care_window
from app.tools.memory_tool import MemoryTool
from app.tools.registry import build_default_tools


def test_refuse_prescription_and_dose():
    d = refuse_memory_note("以后把降压药改成每天两片")
    assert d.refused
    assert d.code == "prescription_content"
    assert "CareTask" in d.display_text or "照护任务" in d.display_text


def test_refuse_escalation_as_memory():
    d = refuse_memory_note("记住以后错过就自动通知家人升级")
    assert d.refused
    assert d.code == "escalation_mutation"


def test_allow_preference_note():
    d = refuse_memory_note("以后记得我喜欢听戏曲，不要放摇滚")
    assert not d.refused


def test_registry_includes_memory():
    reg = build_default_tools()
    assert "memory" in reg
    assert "caretask" in reg


def test_care_window_includes_due_and_undated_active():
    start, end, _date = care_window_bounds(datetime(2026, 7, 11, 4, 0, 0))  # UTC morning → CN afternoon
    assert in_care_window(
        status="due",
        due_at=start + timedelta(hours=2),
        window_start=start,
        window_end=end,
    )
    assert in_care_window(
        status="pending",
        due_at=None,
        window_start=start,
        window_end=end,
    )
    assert in_care_window(
        status="missed",
        due_at=start - timedelta(days=1),
        window_start=start,
        window_end=end,
    )
    assert not in_care_window(
        status="pending",
        due_at=end + timedelta(days=2),
        window_start=start,
        window_end=end,
    )


@pytest.mark.asyncio
async def test_memory_note_refuses_prescription(monkeypatch):
    tool = MemoryTool()
    called = {"store": False}

    async def boom(**kwargs):
        called["store"] = True
        raise AssertionError("must not store")

    monkeypatch.setattr(
        "app.memory.lifecycle_backend.LifecycleMemoryBackend.add",
        boom,
    )
    result = await tool.execute(
        {
            "action": "note",
            "user_id": str(uuid.uuid4()),
            "summary": "把二甲双胍剂量改成每天一片",
            "explicit_user_request": True,
            "query": "以后记得把二甲双胍剂量改成每天一片",
        }
    )
    assert result.status == "success"
    assert result.data["status"] == "refused"
    assert result.data["refusal_code"] == "prescription_content"
    assert called["store"] is False


@pytest.mark.asyncio
async def test_memory_note_pending_honest_display(monkeypatch):
    tool = MemoryTool()
    mid = str(uuid.uuid4())

    async def fake_add(self, **kwargs):
        return mid

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(LifecycleMemoryBackend, "add", fake_add)

    result = await tool.execute(
        {
            "action": "note",
            "user_id": str(uuid.uuid4()),
            "summary": "我喜欢听评书",
            "category": "preference",
            "explicit_user_request": True,
            "query": "以后记得我喜欢听评书",
        }
    )
    assert result.status == "success"
    assert result.data["status"] == "pending"
    assert "已记住" not in result.display_text
    assert "确认" in result.display_text
    assert result.data["memory_id"] == mid


@pytest.mark.asyncio
async def test_memory_recall_empty_on_crisis():
    tool = MemoryTool()
    result = await tool.execute(
        {
            "action": "recall",
            "user_id": str(uuid.uuid4()),
            "query_intent": "我喜欢什么",
            "risk_blocked": True,
            "risk_level": "critical",
        }
    )
    assert result.data["status"] == "empty"
    assert result.data["fragments"] == []
    assert result.data.get("degraded") is True


@pytest.mark.asyncio
async def test_memory_recall_timeout_degraded(monkeypatch):
    adapter = MemoryBusinessAdapter(
        backend=LifecycleMemoryBackend(),
        recall_timeout_ms=50,
    )

    async def slow(**kwargs):
        await asyncio.sleep(1)
        return []

    monkeypatch.setattr(adapter, "_recall_inner", slow)
    result = await adapter.recall(user_id=str(uuid.uuid4()), query_intent="x")
    assert result.status == "timeout"
    assert result.fragments == []
    assert result.degraded is True


@pytest.mark.asyncio
async def test_memory_recall_filters_pending(monkeypatch):
    """Consent gate: only granted rows surface."""
    uid = uuid.uuid4()
    granted = {
        "id": str(uuid.uuid4()),
        "content": "喜欢听评书",
        "purpose": "preference",
        "sensitivity": "general",
        "created_at": datetime.utcnow().isoformat(),
        "importance": 0.9,
        "consent_status": "granted",
        "type": "preference",
    }

    class FakeBackend:
        name = "lifecycle"

        async def add(self, **kwargs):
            return None

        async def search(self, **kwargs):
            return [
                {
                    "id": granted["id"],
                    "content": granted["content"],
                    "score": 0.9,
                    "category": "preference",
                    "consent_status": "granted",
                    "metadata": granted,
                },
                {
                    "id": str(uuid.uuid4()),
                    "content": "pending secret",
                    "score": 0.9,
                    "category": "preference",
                    "consent_status": "pending",
                    "metadata": {"consent_status": "pending", "deletion_state": "active"},
                },
            ]

    async def fake_select(db, *, user_id, purpose="care_continuity", limit=5):
        if purpose == "preference":
            return [granted]
        return []

    monkeypatch.setattr(
        "app.memory.adapter.select_retrievable_memories",
        fake_select,
    )

    class _CM:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.db.session.async_session", lambda: _CM())

    adapter = MemoryBusinessAdapter(backend=FakeBackend())
    result = await adapter.recall(user_id=str(uid), query_intent="评书", limit=5)
    assert result.status == "success"
    assert len(result.fragments) == 1
    assert result.fragments[0]["content"] == "喜欢听评书"


@pytest.mark.asyncio
async def test_caretask_list_defaults_today_scope(monkeypatch):
    from app.tools.caretask_tool import CareTaskTool

    captured = {}

    async def fake_list(**kwargs):
        captured.update(kwargs)
        return [
            {
                "id": str(uuid.uuid4()),
                "title": "降压药",
                "task_type": "medication",
                "status": "due",
                "due_at": datetime.utcnow().isoformat(),
                "notes": "早饭后",
                "care_window_date": "2026-07-11",
            }
        ]

    monkeypatch.setattr("app.tools.caretask_tool.svc.list_care_tasks", fake_list)
    tool = CareTaskTool()
    result = await tool.execute(
        {"action": "list", "user_id": str(uuid.uuid4())}
    )
    assert captured.get("scope") == "today"
    assert result.status == "success"
    assert result.data["dump"][0]["title"] == "降压药"
    assert result.data["dump"][0]["status"] == "due"
    assert "notes" in result.data["dump"][0]


@pytest.mark.asyncio
async def test_tool_execute_blocks_memory_on_high_risk(monkeypatch):
    from app.api.tool_execute import ToolExecuteRequest, tool_execute

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("TOOL_BRIDGE_TOKEN", raising=False)

    resp = await tool_execute(
        ToolExecuteRequest(
            tool_name="memory",
            params={"action": "recall"},
            user_id=str(uuid.uuid4()),
            risk_level="high",
        ),
        authorization=None,
        x_tool_bridge_token=None,
    )
    assert resp.status == "failed"
    assert resp.data["reason"] == "risk_blocked"
