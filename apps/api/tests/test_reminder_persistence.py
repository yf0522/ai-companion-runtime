"""Chat-created reminder persistence tests."""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools.reminder_tool import ReminderTool, parse_time_from_text


@pytest.mark.asyncio
async def test_daily_medicine_reminder_persists(monkeypatch):
    tool = ReminderTool()
    captured: dict = {}

    async def fake_persist(**kwargs):
        captured.update(kwargs)
        return "11111111-1111-1111-1111-111111111111", kwargs["remind_time"]

    monkeypatch.setattr(tool, "_persist_reminder", fake_persist)

    result = await tool.execute(
        {
            "query": "每天晚上8点提醒我吃降压药",
            "user_id": "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
            "session_id": "22222222-2222-2222-2222-222222222222",
            "trace_id": "tr_reminder_demo",
        }
    )

    assert result.status == "success"
    assert result.data["reminder_id"] == "11111111-1111-1111-1111-111111111111"
    assert result.data["repeat_mode"] == "daily"
    assert result.data["hour"] == 20
    assert result.data["minute"] == 0
    assert result.data["schedule_type"] == "daily"
    assert "降压药" in result.data["label"]
    assert captured["schedule_type"] == "daily"
    assert captured["trace_id"] == "tr_reminder_demo"


@pytest.mark.asyncio
async def test_reminder_without_time_asks_clarification():
    tool = ReminderTool()
    result = await tool.execute(
        {
            "query": "提醒我吃药",
            "user_id": "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
        }
    )
    assert result.status == "failed"
    assert result.data["reason"] == "missing_time"
    assert "时间" in result.display_text


@pytest.mark.asyncio
async def test_persist_reminder_writes_db_row(monkeypatch):
    tool = ReminderTool()
    added = []

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def add(self, obj):
            if getattr(obj, "id", None) is None:
                obj.id = uuid.UUID("33333333-3333-3333-3333-333333333333")
            added.append(obj)

        async def commit(self):
            return None

        async def refresh(self, obj):
            return None

    session_module = __import__("app.db.session", fromlist=["async_session"])
    monkeypatch.setattr(session_module, "async_session", lambda: _FakeSession())

    reminder_id, next_fire = await tool._persist_reminder(
        user_id="4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
        title="吃降压药",
        schedule_type="daily",
        remind_time=datetime(2026, 7, 9, 20, 0, 0),
        timer_data={"timer_type": "alarm", "repeat_mode": "daily", "hour": 20, "minute": 0},
        trace_id="tr_db",
    )

    assert reminder_id == "33333333-3333-3333-3333-333333333333"
    assert len(added) == 1
    assert added[0].title == "吃降压药"
    assert added[0].schedule_type == "daily"
    assert added[0].created_by == "chat"
    assert next_fire.hour == 20


@pytest.mark.asyncio
async def test_dispatcher_passes_user_context_to_reminder(monkeypatch):
    from app.tools.dispatcher import ToolDispatcher
    from app.tools.reminder_tool import ReminderTool

    dispatcher = ToolDispatcher()
    dispatcher.register(ReminderTool())  # legacy tool retained for projection tests
    stream = MagicMock()
    stream.send_tool_status = AsyncMock()
    stream.send_tool_result = AsyncMock()
    stream.send_reminder_create = AsyncMock()

    async def fake_execute(params):
        assert params["user_id"] == "user-1"
        assert params["session_id"] == "sess-1"
        assert params["trace_id"] == "tr-1"
        from app.tools.base import ToolResult

        return ToolResult(
            tool_name="reminder",
            status="success",
            display_text="ok",
            data={
                "action": "reminder_create",
                "label": "吃药",
                "reminder_id": "rid",
                "hour": 20,
                "minute": 0,
                "repeat_mode": "daily",
            },
        )

    monkeypatch.setattr(dispatcher._tools["reminder"], "execute", fake_execute)

    results = await dispatcher.dispatch(
        ["reminder"],
        "每天晚上8点提醒我吃药",
        "tr-1",
        stream,
        user_id="user-1",
        session_id="sess-1",
    )
    assert len(results) == 1
    assert results[0].data["reminder_id"] == "rid"
    stream.send_reminder_create.assert_awaited()
    assert stream.send_reminder_create.await_args.args[0]["reminder_id"] == "rid"


def test_parse_time_from_text_evening_chinese_hour():
    parsed = parse_time_from_text("晚上八点")
    assert parsed is not None
    assert parsed.hour == 20
    assert parsed.minute == 0


@pytest.mark.asyncio
async def test_evening_chinese_hour_medicine_reminder(monkeypatch):
    tool = ReminderTool()
    captured: dict = {}

    async def fake_persist(**kwargs):
        captured.update(kwargs)
        return "44444444-4444-4444-4444-444444444444", kwargs["remind_time"]

    monkeypatch.setattr(tool, "_persist_reminder", fake_persist)

    result = await tool.execute(
        {
            "query": "提醒我晚上八点吃降压药",
            "user_id": "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
            "trace_id": "tr_evening_cn",
        }
    )

    assert result.status == "success"
    assert result.data["action"] == "reminder_create"
    assert result.data["hour"] == 20
    assert "降压药" in result.data["label"]
    assert captured["title"] == "吃降压药"


@pytest.mark.asyncio
async def test_dispatcher_emits_reminder_snooze_device_sync(monkeypatch):
    from app.tools.dispatcher import ToolDispatcher
    from app.tools.reminder_tool import ReminderTool

    dispatcher = ToolDispatcher()
    dispatcher.register(ReminderTool())
    stream = MagicMock()
    stream.send_tool_status = AsyncMock()
    stream.send_tool_result = AsyncMock()
    stream.send_reminder_create = AsyncMock()
    stream.send_reminder_snooze = AsyncMock()

    async def fake_execute(params):
        from app.tools.base import ToolResult

        return ToolResult(
            tool_name="reminder",
            status="success",
            display_text="snoozed",
            data={
                "action": "reminder_snooze",
                "reminder_id": "rid-snooze",
                "label": "吃降压药",
                "snooze_minutes": 30,
                "next_fire_at": "2026-07-09T20:30:00",
            },
        )

    monkeypatch.setattr(dispatcher._tools["reminder"], "execute", fake_execute)

    await dispatcher.dispatch(
        ["reminder"],
        "晚点再吃",
        "tr-snooze",
        stream,
        user_id="user-1",
        session_id="sess-1",
    )

    stream.send_reminder_snooze.assert_awaited_once()
    payload = stream.send_reminder_snooze.await_args.args[0]
    assert payload["reminder_id"] == "rid-snooze"
    assert payload["snooze_minutes"] == 30
    stream.send_reminder_create.assert_not_awaited()
