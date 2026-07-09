"""CareTask domain + tool + honesty contract tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.tools.caretask_service import (
    CareTaskTransitionError,
    assert_transition,
    can_transition,
    infer_initial_status,
    refresh_status,
)
from app.tools.caretask_tool import CareTaskTool
from app.tools.honesty import enforce_no_verbal_promise, response_claims_tool_success
from app.tools.base import ToolResult
from app.engines.base import AnalyzerInput
from app.engines.intent_engine import IntentEngine


def test_state_machine_transitions():
    assert can_transition("pending", "due")
    assert can_transition("due", "done")
    assert can_transition("due", "snoozed")
    assert can_transition("snoozed", "due")
    assert can_transition("pending", "cancelled")
    assert not can_transition("done", "pending")
    assert not can_transition("cancelled", "done")
    with pytest.raises(CareTaskTransitionError):
        assert_transition("done", "snoozed")


def test_infer_and_refresh_status():
    now = datetime(2026, 7, 9, 12, 0, 0)
    assert infer_initial_status(now + timedelta(hours=1), now) == "pending"
    assert infer_initial_status(now - timedelta(minutes=1), now) == "due"
    assert refresh_status("pending", now - timedelta(minutes=5), None, now) == "due"
    assert refresh_status("done", now - timedelta(hours=1), None, now) == "done"
    assert (
        refresh_status("snoozed", now + timedelta(hours=1), now - timedelta(minutes=1), now)
        == "pending"
    )


def test_response_claims_tool_success():
    assert response_claims_tool_success("已设置提醒：吃药")
    assert response_claims_tool_success("I've set a reminder for you")
    assert not response_claims_tool_success("抱歉，保存失败了")


def test_enforce_no_verbal_promise_rewrites_success_claim():
    failed = [
        ToolResult(
            tool_name="caretask",
            status="failed",
            display_text="照护任务处理失败，请稍后重试",
            data={"reason": "persist_failed"},
        )
    ]
    text = "好的，已帮你创建吃药任务了"
    out = enforce_no_verbal_promise(text, failed)
    assert out != text
    assert "没有成功" in out or "失败" in out
    assert "已帮你创建" not in out


def test_enforce_no_verbal_promise_keeps_honest_text():
    failed = [
        ToolResult(tool_name="caretask", status="failed", display_text="保存失败")
    ]
    text = "抱歉，刚才没有保存成功"
    assert enforce_no_verbal_promise(text, failed) == text


@pytest.mark.asyncio
async def test_intent_prefers_caretask_for_medicine():
    engine = IntentEngine()
    result = await engine.analyze(
        AnalyzerInput(
            user_id="u",
            session_id="s",
            message="每天晚上8点提醒我吃降压药",
            trace_id="t1",
        )
    )
    assert "caretask" in result.tool_needs
    assert "reminder" not in result.tool_needs


@pytest.mark.asyncio
async def test_intent_snooze_routes_to_caretask():
    engine = IntentEngine()
    result = await engine.analyze(
        AnalyzerInput(
            user_id="u",
            session_id="s",
            message="晚点再吃",
            trace_id="t1",
        )
    )
    assert "caretask" in result.tool_needs


@pytest.mark.asyncio
async def test_caretask_create_links_reminder(monkeypatch):
    tool = CareTaskTool()
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "title": kwargs["title"],
            "task_type": kwargs["task_type"],
            "status": "pending",
            "due_at": kwargs["due_at"].isoformat() if kwargs.get("due_at") else None,
            "reminder_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "snooze_until": None,
            "notes": kwargs.get("notes"),
            "created_by": "chat",
            "completed_at": None,
            "created_at": None,
            "user_id": kwargs["user_id"],
        }

    monkeypatch.setattr("app.tools.caretask_tool.svc.create_care_task", fake_create)
    result = await tool.execute(
        {
            "action": "create",
            "query": "每天晚上8点提醒我吃降压药",
            "user_id": "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
            "trace_id": "tr_care",
        }
    )
    assert result.status == "success"
    assert result.data["action"] == "caretask_create"
    assert captured["link_reminder"] is True
    assert captured["due_at"] is not None
    assert "降压药" in captured["title"] or "吃" in captured["title"]


@pytest.mark.asyncio
async def test_caretask_complete_and_snooze(monkeypatch):
    tool = CareTaskTool()

    async def fake_list(**kwargs):
        return [
            {
                "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "title": "吃降压药",
                "status": "due",
                "task_type": "medication",
                "due_at": None,
                "reminder_id": None,
                "snooze_until": None,
                "notes": None,
                "created_by": "chat",
                "completed_at": None,
                "created_at": None,
                "user_id": kwargs["user_id"],
            }
        ]

    async def fake_complete(**kwargs):
        return {
            "id": kwargs["task_id"],
            "title": "吃降压药",
            "status": "done",
            "task_type": "medication",
            "due_at": None,
            "reminder_id": None,
            "snooze_until": None,
            "notes": None,
            "created_by": "chat",
            "completed_at": datetime.utcnow().isoformat(),
            "created_at": None,
            "user_id": kwargs["user_id"],
        }

    async def fake_snooze(**kwargs):
        return {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "title": "吃降压药",
            "status": "snoozed",
            "task_type": "medication",
            "due_at": (datetime.utcnow() + timedelta(minutes=30)).isoformat(),
            "reminder_id": None,
            "snooze_until": (datetime.utcnow() + timedelta(minutes=30)).isoformat(),
            "notes": None,
            "created_by": "chat",
            "completed_at": None,
            "created_at": None,
            "user_id": kwargs["user_id"],
            "snooze_minutes": kwargs["minutes"],
        }

    monkeypatch.setattr("app.tools.caretask_tool.svc.list_care_tasks", fake_list)
    monkeypatch.setattr("app.tools.caretask_tool.svc.complete_care_task", fake_complete)
    monkeypatch.setattr("app.tools.caretask_tool.svc.snooze_care_task", fake_snooze)

    done = await tool.execute(
        {"action": "complete", "user_id": str(uuid.uuid4())}
    )
    assert done.status == "success"
    assert done.data["task"]["status"] == "done"

    snooze = await tool.execute(
        {"action": "snooze", "query": "晚点再吃", "user_id": str(uuid.uuid4())}
    )
    assert snooze.status == "success"
    assert snooze.data["task"]["status"] == "snoozed"


@pytest.mark.asyncio
async def test_caretask_failed_does_not_claim_success():
    tool = CareTaskTool()
    result = await tool.execute({"action": "create", "query": "吃药"})
    assert result.status == "failed"
    assert not response_claims_tool_success(result.display_text)


@pytest.mark.asyncio
async def test_tool_bridge_execute_endpoint():
    from app.api.tool_execute import ToolExecuteRequest, tool_execute

    # Missing user should fail caretask create honestly
    resp = await tool_execute(
        ToolExecuteRequest(tool_name="caretask", params={"action": "list"}),
        authorization=None,
        x_tool_bridge_token=None,
    )
    assert resp.status == "failed"
    assert resp.data and resp.data.get("reason") == "missing_user"


@pytest.mark.asyncio
async def test_tool_bridge_risk_blocks():
    from app.api.tool_execute import ToolExecuteRequest, tool_execute

    resp = await tool_execute(
        ToolExecuteRequest(
            tool_name="caretask",
            params={"action": "list"},
            user_id=str(uuid.uuid4()),
            risk_level="critical",
        ),
        authorization=None,
        x_tool_bridge_token=None,
    )
    assert resp.status == "failed"
    assert resp.data["reason"] == "risk_blocked"


@pytest.mark.asyncio
async def test_registry_includes_caretask():
    from app.tools.registry import get_tool_registry, list_tool_schemas

    reg = get_tool_registry()
    assert "caretask" in reg
    names = {s["name"] for s in list_tool_schemas()}
    assert "caretask" in names
