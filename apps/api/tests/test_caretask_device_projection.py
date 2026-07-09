"""CareTask → device reminder_* projection + daily recurrence."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools.base import ToolResult
from app.tools.device_projection import (
    caretask_device_cancel_payload,
    caretask_device_create_payload,
    caretask_device_snooze_payload,
    infer_schedule_type_from_utterance,
)
from app.tools.dispatcher import ToolDispatcher


def test_infer_schedule_type_daily_vs_once():
    assert infer_schedule_type_from_utterance("每天晚上8点吃降压药") == "daily"
    assert infer_schedule_type_from_utterance("每日早上吃药") == "daily"
    assert infer_schedule_type_from_utterance("晚上八点吃降压药") == "once"
    assert infer_schedule_type_from_utterance(None) == "once"


def test_caretask_device_create_payload_daily():
    task = {
        "id": "ct-1",
        "title": "吃降压药",
        "reminder_id": "rid-1",
        "due_at": "2026-07-10T20:00:00",
        "schedule_type": "daily",
    }
    payload = caretask_device_create_payload(task)
    assert payload is not None
    assert payload["reminder_id"] == "rid-1"
    assert payload["repeat_mode"] == "daily"
    assert payload["schedule_type"] == "daily"
    assert payload["hour"] == 20
    assert payload["minute"] == 0
    assert payload["caretask_id"] == "ct-1"


def test_caretask_device_create_infers_daily_from_query():
    task = {
        "id": "ct-2",
        "title": "吃降压药",
        "reminder_id": "rid-2",
        "due_at": "2026-07-10T20:00:00",
    }
    payload = caretask_device_create_payload(
        task, query="每天晚上8点提醒我吃降压药"
    )
    assert payload is not None
    assert payload["repeat_mode"] == "daily"


def test_caretask_device_snooze_reads_nested_minutes():
    data = {
        "action": "caretask_snooze",
        "task": {
            "id": "ct-3",
            "title": "吃降压药",
            "reminder_id": "rid-3",
            "snooze_until": "2026-07-10T20:30:00",
            "snooze_minutes": 30,
        },
    }
    payload = caretask_device_snooze_payload(data)
    assert payload is not None
    assert payload["snooze_minutes"] == 30
    assert payload["reminder_id"] == "rid-3"


def test_caretask_device_cancel_payload():
    task = {
        "id": "ct-4",
        "title": "吃降压药",
        "reminder_id": "rid-4",
        "status": "done",
    }
    payload = caretask_device_cancel_payload(task)
    assert payload is not None
    assert payload["reminder_id"] == "rid-4"
    assert payload["reason"] == "done"


def _mock_stream() -> MagicMock:
    stream = MagicMock()
    stream.send_tool_status = AsyncMock()
    stream.send_tool_result = AsyncMock()
    stream.send_reminder_create = AsyncMock()
    stream.send_reminder_snooze = AsyncMock()
    stream.send_reminder_cancel = AsyncMock()
    return stream


@pytest.mark.asyncio
async def test_dispatcher_projects_caretask_create_daily(monkeypatch):
    dispatcher = ToolDispatcher()
    stream = _mock_stream()

    async def fake_execute(params):
        return ToolResult(
            tool_name="caretask",
            status="success",
            display_text="created",
            data={
                "action": "caretask_create",
                "schedule_type": "daily",
                "query": "每天晚上8点吃降压药",
                "task": {
                    "id": "ct-create",
                    "title": "吃降压药",
                    "reminder_id": "rid-create",
                    "due_at": "2026-07-10T20:00:00",
                    "schedule_type": "daily",
                },
            },
        )

    monkeypatch.setattr(dispatcher._tools["caretask"], "execute", fake_execute)
    await dispatcher.dispatch(
        ["caretask"],
        "每天晚上8点吃降压药",
        "tr-ct-create",
        stream,
        user_id="user-1",
        session_id="sess-1",
    )

    stream.send_reminder_create.assert_awaited_once()
    payload = stream.send_reminder_create.await_args.args[0]
    assert payload["reminder_id"] == "rid-create"
    assert payload["repeat_mode"] == "daily"
    assert payload["hour"] == 20
    stream.send_reminder_snooze.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatcher_projects_schedule_updated_not_plain_reuse(monkeypatch):
    dispatcher = ToolDispatcher()
    stream = _mock_stream()

    async def fake_reuse_no_update(params):
        return ToolResult(
            tool_name="caretask",
            status="success",
            display_text="reuse",
            data={
                "action": "caretask_reuse",
                "schedule_updated": False,
                "task": {
                    "id": "ct-r",
                    "title": "吃降压药",
                    "reminder_id": "rid-r",
                    "due_at": "2026-07-10T20:00:00",
                },
            },
        )

    monkeypatch.setattr(dispatcher._tools["caretask"], "execute", fake_reuse_no_update)
    await dispatcher.dispatch(
        ["caretask"], "吃降压药", "tr-reuse", stream, user_id="u1", session_id="s1"
    )
    stream.send_reminder_create.assert_not_awaited()

    async def fake_schedule_updated(params):
        return ToolResult(
            tool_name="caretask",
            status="success",
            display_text="updated",
            data={
                "action": "caretask_schedule_updated",
                "schedule_updated": True,
                "schedule_type": "daily",
                "task": {
                    "id": "ct-u",
                    "title": "吃降压药",
                    "reminder_id": "rid-u",
                    "due_at": "2026-07-10T21:00:00",
                    "schedule_type": "daily",
                },
            },
        )

    monkeypatch.setattr(dispatcher._tools["caretask"], "execute", fake_schedule_updated)
    await dispatcher.dispatch(
        ["caretask"],
        "每天晚上9点吃降压药",
        "tr-upd",
        stream,
        user_id="u1",
        session_id="s1",
    )
    stream.send_reminder_create.assert_awaited_once()
    assert stream.send_reminder_create.await_args.args[0]["hour"] == 21


@pytest.mark.asyncio
async def test_dispatcher_caretask_snooze_minutes_not_none(monkeypatch):
    dispatcher = ToolDispatcher()
    stream = _mock_stream()

    async def fake_execute(params):
        return ToolResult(
            tool_name="caretask",
            status="success",
            display_text="snoozed",
            data={
                "action": "caretask_snooze",
                "snooze_minutes": 30,
                "task": {
                    "id": "ct-s",
                    "title": "吃降压药",
                    "reminder_id": "rid-s",
                    "snooze_until": "2026-07-10T20:30:00",
                    "snooze_minutes": 30,
                },
            },
        )

    monkeypatch.setattr(dispatcher._tools["caretask"], "execute", fake_execute)
    await dispatcher.dispatch(
        ["caretask"], "晚点再吃", "tr-snooze", stream, user_id="u1", session_id="s1"
    )
    stream.send_reminder_snooze.assert_awaited_once()
    payload = stream.send_reminder_snooze.await_args.args[0]
    assert payload["snooze_minutes"] == 30
    assert payload["reminder_id"] == "rid-s"


@pytest.mark.asyncio
async def test_dispatcher_caretask_complete_and_cancel_emit_cancel(monkeypatch):
    dispatcher = ToolDispatcher()
    stream = _mock_stream()

    async def fake_complete(params):
        return ToolResult(
            tool_name="caretask",
            status="success",
            display_text="done",
            data={
                "action": "caretask_complete",
                "task": {
                    "id": "ct-c",
                    "title": "吃降压药",
                    "reminder_id": "rid-c",
                    "status": "done",
                },
            },
        )

    monkeypatch.setattr(dispatcher._tools["caretask"], "execute", fake_complete)
    await dispatcher.dispatch(
        ["caretask"], "吃完了", "tr-done", stream, user_id="u1", session_id="s1"
    )
    stream.send_reminder_cancel.assert_awaited_once()
    assert stream.send_reminder_cancel.await_args.args[0]["reason"] == "done"

    stream.send_reminder_cancel.reset_mock()

    async def fake_cancel(params):
        return ToolResult(
            tool_name="caretask",
            status="success",
            display_text="cancelled",
            data={
                "action": "caretask_cancel",
                "task": {
                    "id": "ct-x",
                    "title": "吃降压药",
                    "reminder_id": "rid-x",
                    "status": "cancelled",
                },
            },
        )

    monkeypatch.setattr(dispatcher._tools["caretask"], "execute", fake_cancel)
    await dispatcher.dispatch(
        ["caretask"], "取消吃药", "tr-cancel", stream, user_id="u1", session_id="s1"
    )
    stream.send_reminder_cancel.assert_awaited_once()
    assert stream.send_reminder_cancel.await_args.args[0]["reason"] == "cancelled"
