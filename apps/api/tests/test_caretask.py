"""CareTask domain + tool + honesty contract tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.tools.caretask_service import (
    CareTaskTransitionError,
    assert_transition,
    can_transition,
    infer_initial_status,
    normalize_title,
    refresh_status,
    title_fingerprint,
)
from app.tools.caretask_tool import CareTaskTool, _infer_action_from_query
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


@pytest.mark.parametrize(
    "query",
    [
        "今日任务",
        "我问你今天有什么照护任务",
        "我今天有哪些照护任务",
        "请列出今天的照护任务",
        "我今天需要做什么",
        "吃药",
    ],
)
def test_caretask_queries_default_to_read_only(query):
    assert _infer_action_from_query(query) == "list"


@pytest.mark.parametrize(
    "query",
    [
        "提醒我晚上八点吃药",
        "帮我记一下吃降糖药",
        "新增一个下周复诊任务",
    ],
)
def test_caretask_creation_requires_an_explicit_write_cue(query):
    assert _infer_action_from_query(query) == "create"


@pytest.mark.asyncio
async def test_caretask_query_without_model_action_never_calls_create(monkeypatch):
    tool = CareTaskTool()
    list_result = ToolResult(
        tool_name="caretask",
        status="success",
        display_text="当前没有待处理的照护任务",
        data={"action": "caretask_list", "tasks": []},
    )
    list_call = AsyncMock(return_value=list_result)
    create_call = AsyncMock()
    monkeypatch.setattr(tool, "_list", list_call)
    monkeypatch.setattr(tool, "_create", create_call)

    result = await tool.execute(
        {
            "query": "我问你今天有什么照护任务",
            "user_id": str(uuid.uuid4()),
        }
    )

    assert result.data["action"] == "caretask_list"
    list_call.assert_awaited_once()
    create_call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "mutation_method"),
    [
        ("create", "_create"),
        ("complete", "_complete"),
        ("cancel", "_cancel"),
        ("snooze", "_snooze"),
        ("missed", "_missed"),
    ],
)
async def test_caretask_read_query_overrides_any_model_mutation(
    monkeypatch,
    action,
    mutation_method,
):
    tool = CareTaskTool()
    list_result = ToolResult(
        tool_name="caretask",
        status="success",
        display_text="当前没有待处理的照护任务",
        data={"action": "caretask_list", "tasks": []},
    )
    list_call = AsyncMock(return_value=list_result)
    mutation_call = AsyncMock()
    monkeypatch.setattr(tool, "_list", list_call)
    monkeypatch.setattr(tool, mutation_method, mutation_call)

    result = await tool.execute(
        {
            "action": action,
            "query": "我问你今天有什么照护任务",
            "title": "模型臆造的任务",
            "user_id": str(uuid.uuid4()),
        }
    )

    assert result.data["action"] == "caretask_list"
    list_call.assert_awaited_once()
    mutation_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_intent_routes_explicit_family_help_request_to_contact_tool():
    result = await IntentEngine().analyze(
        AnalyzerInput(
            user_id="u",
            session_id="s",
            message="我想让家人知道我需要帮助",
            trace_id="t-contact",
        )
    )
    assert result.primary_intent == "task"
    assert result.tool_needs == ["contact"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "我不想让家人知道",
        "我已经告诉家人了",
        "医生让我联系家人",
        "我刚联系过女儿",
        "联系家人了吗",
        "我想告诉家人最近挺好的",
    ],
)
async def test_intent_does_not_contact_family_without_an_explicit_request(message):
    result = await IntentEngine().analyze(
        AnalyzerInput(
            user_id="u",
            session_id="s",
            message=message,
            trace_id="t-contact-negative",
        )
    )
    assert "contact" not in result.tool_needs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["联系家人", "我想让家人知道我需要帮助", "请家人联系我", "我想请你通知女儿"],
)
async def test_intent_routes_only_explicit_family_contact_commands(message):
    result = await IntentEngine().analyze(
        AnalyzerInput(
            user_id="u",
            session_id="s",
            message=message,
            trace_id="t-contact-explicit",
        )
    )
    assert result.tool_needs == ["contact"]


def test_normalize_title_and_fingerprint():
    assert normalize_title("提醒我吃降压药") == normalize_title("帮我吃降压药")
    assert normalize_title("每天晚上8点提醒我吃降压药") == normalize_title("帮我记一下吃降压药")
    assert normalize_title("每天晚上8点提醒我吃降压药") == "吃降压药"
    assert normalize_title("服用降压药") == "吃降压药"
    assert normalize_title("服药降压药") == "吃降压药"
    assert "降压药" in normalize_title("每天晚上提醒我吃降压药吧")
    fp1 = title_fingerprint("吃降压药", "medication", None)
    fp2 = title_fingerprint("提醒我吃降压药", "medication", None)
    # Timed vs undated must share identity (due ignored)
    fp3 = title_fingerprint("吃降压药", "medication", datetime(2026, 7, 9, 20, 0, 0))
    assert fp1 == fp2 == fp3
    assert "|" not in fp1.split("|", 1)[1] or fp1.count("|") == 1


@pytest.mark.asyncio
async def test_caretask_create_reuses_active_duplicate(monkeypatch):
    tool = CareTaskTool()
    calls = {"n": 0}

    async def fake_create(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "title": kwargs["title"],
                "task_type": kwargs["task_type"],
                "status": "pending",
                "due_at": None,
                "reminder_id": None,
                "snooze_until": None,
                "notes": None,
                "created_by": "chat",
                "completed_at": None,
                "created_at": None,
                "user_id": kwargs["user_id"],
                "_action": "caretask_create",
            }
        return {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "title": kwargs["title"],
            "task_type": kwargs["task_type"],
            "status": "pending",
            "due_at": None,
            "reminder_id": None,
            "snooze_until": None,
            "notes": None,
            "created_by": "chat",
            "completed_at": None,
            "created_at": None,
            "user_id": kwargs["user_id"],
            "_action": "caretask_reuse",
            "_schedule_updated": False,
        }

    monkeypatch.setattr("app.tools.caretask_tool.svc.create_care_task", fake_create)
    uid = "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf"
    first = await tool.execute(
        {"action": "create", "query": "晚上8点提醒我吃降压药", "user_id": uid}
    )
    second = await tool.execute(
        {"action": "create", "query": "帮我记一下吃降压药", "user_id": uid}
    )
    assert first.status == "success"
    assert first.data["action"] == "caretask_create"
    assert second.status == "success"
    assert second.data["action"] == "caretask_reuse"
    assert "已经记过" in second.display_text
    assert "继续为您保留" in second.display_text
    assert "pending" not in second.display_text.lower()
    assert "未重复创建" not in second.display_text


@pytest.mark.asyncio
async def test_caretask_create_reuses_when_due_differs(monkeypatch):
    """Timed then undated (or vice versa) must reuse — never silent double-create."""
    from app.tools import caretask_service as svc

    existing = {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "title": "吃降压药",
        "task_type": "medication",
        "status": "pending",
        "due_at": "2026-07-09T20:00:00",
        "reminder_id": None,
        "snooze_until": None,
        "notes": None,
        "created_by": "chat",
        "completed_at": None,
        "created_at": None,
        "user_id": "u1",
    }

    async def fake_find(**kwargs):
        return existing

    async def fake_near(**kwargs):
        return []

    monkeypatch.setattr(svc, "find_active_by_fingerprint", fake_find)
    monkeypatch.setattr(svc, "find_near_duplicate_candidates", fake_near)

    result = await svc.create_care_task(
        user_id="u1",
        title="吃降压药",
        task_type="medication",
        due_at=None,
    )
    assert result["_action"] == "caretask_reuse"
    assert result["id"] == existing["id"]


@pytest.mark.asyncio
async def test_caretask_create_updates_schedule_on_reuse(monkeypatch):
    from app.tools import caretask_service as svc

    existing = {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "title": "吃降压药",
        "task_type": "medication",
        "status": "pending",
        "due_at": None,
        "reminder_id": None,
        "snooze_until": None,
        "notes": None,
        "created_by": "chat",
        "completed_at": None,
        "created_at": None,
        "user_id": "u1",
    }
    new_due = datetime(2026, 7, 9, 20, 0, 0)

    async def fake_find(**kwargs):
        return existing

    async def fake_near(**kwargs):
        return []

    async def fake_update(**kwargs):
        return {
            **existing,
            "due_at": new_due.isoformat(),
            "status": "pending",
        }

    monkeypatch.setattr(svc, "find_active_by_fingerprint", fake_find)
    monkeypatch.setattr(svc, "find_near_duplicate_candidates", fake_near)
    monkeypatch.setattr(svc, "_update_task_schedule", fake_update)

    result = await svc.create_care_task(
        user_id="u1",
        title="吃降压药",
        task_type="medication",
        due_at=new_due,
    )
    assert result["_action"] == "caretask_reuse"
    assert result["_schedule_updated"] is True
    assert result["due_at"] == new_due.isoformat()


@pytest.mark.asyncio
async def test_caretask_create_clarifies_near_duplicate_different_title(monkeypatch):
    tool = CareTaskTool()

    async def fake_create(**kwargs):
        return {
            "_action": "caretask_clarify_create",
            "candidates": [
                {
                    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "title": "吃降压药",
                    "status": "pending",
                    "due_at": "2026-07-09T20:00:00",
                    "task_type": "medication",
                }
            ],
            "proposed": {
                "title": kwargs["title"],
                "task_type": kwargs["task_type"],
                "due_at": kwargs["due_at"].isoformat() if kwargs.get("due_at") else None,
            },
        }

    monkeypatch.setattr("app.tools.caretask_tool.svc.create_care_task", fake_create)
    result = await tool.execute(
        {
            "action": "create",
            "query": "晚上8点提醒我吃降糖药",
            "user_id": str(uuid.uuid4()),
        }
    )
    assert result.status == "needs_clarification"
    assert result.data["action"] == "caretask_clarify_create"
    assert result.data["candidates"]


@pytest.mark.asyncio
async def test_complete_ambiguous_returns_needs_clarification_no_mutation(monkeypatch):
    tool = CareTaskTool()
    mutated = {"called": False}

    async def fake_resolve(**kwargs):
        from app.tools.caretask_service import ResolveResult

        return ResolveResult(
            kind="many",
            candidates=[
                {
                    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "title": "吃降压药",
                    "status": "pending",
                    "due_at": None,
                    "task_type": "medication",
                },
                {
                    "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "title": "吃降糖药",
                    "status": "pending",
                    "due_at": None,
                    "task_type": "medication",
                },
            ],
        )

    async def fake_complete(**kwargs):
        mutated["called"] = True
        raise AssertionError("should not mutate on ambiguous ref")

    monkeypatch.setattr("app.tools.caretask_tool.svc.resolve_task_ref", fake_resolve)
    monkeypatch.setattr("app.tools.caretask_tool.svc.complete_care_task", fake_complete)
    result = await tool.execute(
        {"action": "complete", "query": "药我吃过了", "user_id": str(uuid.uuid4())}
    )
    assert result.status == "needs_clarification"
    assert mutated["called"] is False
    assert "多个" in result.display_text


@pytest.mark.asyncio
async def test_cancel_without_id_lists_candidates(monkeypatch):
    tool = CareTaskTool()

    async def fake_resolve(**kwargs):
        from app.tools.caretask_service import ResolveResult

        return ResolveResult(
            kind="many",
            candidates=[
                {
                    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "title": "吃降压药",
                    "status": "pending",
                    "due_at": None,
                    "task_type": "medication",
                },
                {
                    "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "title": "复诊",
                    "status": "pending",
                    "due_at": None,
                    "task_type": "appointment",
                },
            ],
        )

    monkeypatch.setattr("app.tools.caretask_tool.svc.resolve_task_ref", fake_resolve)
    result = await tool.execute(
        {"action": "cancel", "query": "取消吃药提醒", "user_id": str(uuid.uuid4())}
    )
    assert result.status == "needs_clarification"
    assert len(result.data["candidates"]) == 2


@pytest.mark.asyncio
async def test_cancel_generic_med_with_multiple_tasks_clarifies(monkeypatch):
    """P0 regression: 「取消吃药提醒」 must not silent-cancel when ≥2 actives.

    Previously substring match bound to a lone generic 「吃药」 / 「九点吃药」 title.
    """
    from app.tools import caretask_service as svc

    tasks = [
        {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "title": "吃降压药",
            "status": "pending",
            "due_at": None,
            "task_type": "medication",
        },
        {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "title": "吃降糖药",
            "status": "pending",
            "due_at": None,
            "task_type": "medication",
        },
        {
            "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "title": "九点吃药",
            "status": "pending",
            "due_at": None,
            "task_type": "medication",
        },
    ]

    async def fake_list(**kwargs):
        return tasks

    monkeypatch.setattr(svc, "list_care_tasks", fake_list)
    resolved = await svc.resolve_task_ref(
        user_id=str(uuid.uuid4()),
        query="取消吃药提醒",
    )
    assert resolved.kind == "many"
    assert len(resolved.candidates or []) >= 2

    tool = CareTaskTool()
    mutated = {"called": False}

    async def fake_cancel(**kwargs):
        mutated["called"] = True
        raise AssertionError("must not cancel on ambiguous generic med ref")

    monkeypatch.setattr("app.tools.caretask_tool.svc.cancel_care_task", fake_cancel)
    result = await tool.execute(
        {
            "action": "cancel",
            "query": "取消吃药提醒",
            "user_id": str(uuid.uuid4()),
        }
    )
    assert result.status == "needs_clarification"
    assert mutated["called"] is False
    assert "多个" in result.display_text or "哪一个" in result.display_text


def test_extract_resolve_hint_strips_cancel_verb():
    from app.tools.caretask_service import extract_resolve_hint, is_generic_med_hint

    assert extract_resolve_hint(None, "取消吃药提醒") == "吃药"
    assert is_generic_med_hint(extract_resolve_hint(None, "取消吃药提醒"))
    assert extract_resolve_hint(None, "取消降压药") == "降压药"
    assert not is_generic_med_hint(extract_resolve_hint(None, "取消降压药"))
    assert extract_resolve_hint(None, "降压药我吃过了") == "降压药"
    assert not is_generic_med_hint(extract_resolve_hint(None, "降压药我吃过了"))


@pytest.mark.asyncio
async def test_resolve_specific_med_does_not_broaden_to_unrelated(monkeypatch):
    """P0: after 降压药 done, 「降压药我吃过了」 must not offer 降糖药/量血压."""
    from app.tools import caretask_service as svc

    active = [
        {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "title": "降糖药",
            "status": "pending",
            "due_at": None,
            "task_type": "medication",
        },
        {
            "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "title": "量血压",
            "status": "pending",
            "due_at": None,
            "task_type": "medication",
        },
    ]
    all_rows = active + [
        {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "title": "降压药",
            "status": "done",
            "due_at": None,
            "task_type": "medication",
        },
    ]

    async def fake_list(**kwargs):
        if kwargs.get("include_terminal"):
            return all_rows
        return active

    monkeypatch.setattr(svc, "list_care_tasks", fake_list)
    resolved = await svc.resolve_task_ref(
        user_id=str(uuid.uuid4()),
        query="降压药我吃过了",
    )
    assert resolved.kind == "none"
    assert resolved.already_done is True
    assert resolved.hint == "降压药"
    titles = {c["title"] for c in (resolved.candidates or [])}
    assert "降糖药" not in titles
    assert "量血压" not in titles

    tool = CareTaskTool()
    result = await tool.execute(
        {
            "action": "complete",
            "query": "降压药我吃过了",
            "user_id": str(uuid.uuid4()),
        }
    )
    assert result.status == "success"
    assert result.data["action"] == "caretask_already_done"
    assert "降压药" in result.display_text
    assert "降糖药" not in result.display_text
    assert "量血压" not in result.display_text
    assert "pending" not in result.display_text.lower()


@pytest.mark.asyncio
async def test_resolve_specific_pending_med_matches(monkeypatch):
    from app.tools import caretask_service as svc

    active = [
        {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "title": "吃降压药",
            "status": "pending",
            "due_at": None,
            "task_type": "medication",
        },
        {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "title": "降糖药",
            "status": "pending",
            "due_at": None,
            "task_type": "medication",
        },
    ]

    async def fake_list(**kwargs):
        return active

    monkeypatch.setattr(svc, "list_care_tasks", fake_list)
    resolved = await svc.resolve_task_ref(
        user_id=str(uuid.uuid4()),
        query="降压药我吃过了",
    )
    assert resolved.kind == "one"
    assert resolved.task is not None
    assert "降压" in resolved.task["title"]


@pytest.mark.asyncio
async def test_resolve_task_id_from_clarify_followup(monkeypatch):
    from app.tools import caretask_service as svc

    tid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    active = [
        {
            "id": tid,
            "title": "降糖药",
            "status": "pending",
            "due_at": None,
            "task_type": "medication",
        },
        {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "title": "量血压",
            "status": "pending",
            "due_at": None,
            "task_type": "medication",
        },
    ]

    async def fake_list(**kwargs):
        return active

    monkeypatch.setattr(svc, "list_care_tasks", fake_list)
    resolved = await svc.resolve_task_ref(
        user_id=str(uuid.uuid4()),
        query=f"取消任务 降糖药 id={tid}",
    )
    assert resolved.kind == "one"
    assert resolved.task is not None
    assert resolved.task["id"] == tid


def test_honesty_does_not_claim_success_on_clarification():
    clarify = [
        ToolResult(
            tool_name="caretask",
            status="needs_clarification",
            display_text="找到多个照护任务，请告诉我要取消哪一个",
            data={"action": "caretask_cancel"},
        )
    ]
    text = "好的，已帮你取消吃药任务了"
    out = enforce_no_verbal_promise(text, clarify)
    assert out != text
    assert "已帮你取消" not in out
    assert "多个" in out or "确认" in out or "取消" in out


def test_honesty_rewrites_reuse_as_already_recorded():
    reuse = [
        ToolResult(
            tool_name="caretask",
            status="success",
            display_text="您已经有吃降压药的提醒了，我帮您沿用，没有重复创建。",
            data={"action": "caretask_reuse"},
        )
    ]
    claimed = "好的，已经为您记录了吃降压药"
    out = enforce_no_verbal_promise(claimed, reuse)
    assert "沿用" in out or "已经有" in out
    assert "pending" not in out.lower()
    assert "未重复创建" not in out
    assert "已经为您记录了" not in out


def test_honesty_rewrites_false_reminded_now_on_reuse():
    reuse = [
        ToolResult(
            tool_name="caretask",
            status="success",
            display_text="您已经有吃降糖药的提醒了，我帮您沿用，没有重复创建。",
            data={"action": "caretask_reuse"},
        )
    ]
    claimed = "我已经提醒你吃降糖药了"
    out = enforce_no_verbal_promise(claimed, reuse)
    assert "沿用" in out or "已经有" in out
    assert "我已经提醒你" not in out


def test_reuse_display_text_has_no_tech_jargon():
    from app.tools.caretask_tool import _reuse_display

    text = _reuse_display("降糖药", schedule_updated=False)
    assert "继续为您保留" in text
    assert "提醒时间" not in text
    assert "pending" not in text.lower()
    assert "未重复创建" not in text
    assert "状态" not in text


@pytest.mark.asyncio
async def test_caretask_vague_reminder_requires_time_without_mutation(monkeypatch):
    tool = CareTaskTool()
    create = AsyncMock()
    monkeypatch.setattr("app.tools.caretask_tool.svc.create_care_task", create)
    result = await tool.execute(
        {
            "action": "create",
            "title": "吃降糖药",
            "due_at": "2023-10-27T08:00:00",
            "query": "提醒我吃降糖药",
            "user_id": str(uuid.uuid4()),
        }
    )
    assert result.status == "needs_clarification"
    assert result.data["reason"] == "reminder_time_required"
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_caretask_undated_general_note_remains_allowed(monkeypatch):
    tool = CareTaskTool()
    create = AsyncMock(return_value={
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "title": "带医保卡",
        "task_type": "other",
        "status": "pending",
        "due_at": None,
        "reminder_id": None,
        "_action": "caretask_create",
    })
    monkeypatch.setattr("app.tools.caretask_tool.svc.create_care_task", create)
    result = await tool.execute({
        "action": "create", "query": "帮我记一下带医保卡", "task_type": "other",
        "user_id": str(uuid.uuid4()),
    })
    assert result.status == "success"
    assert create.await_args.kwargs["due_at"] is None
    assert create.await_args.kwargs["link_reminder"] is False


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
            "_action": "caretask_create",
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
    task = {
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
        "user_id": "u",
    }

    async def fake_resolve(**kwargs):
        from app.tools.caretask_service import ResolveResult

        return ResolveResult(kind="one", task={**task, "user_id": kwargs["user_id"]})

    async def fake_complete(**kwargs):
        return {
            **task,
            "id": kwargs["task_id"],
            "status": "done",
            "completed_at": datetime.utcnow().isoformat(),
            "user_id": kwargs["user_id"],
        }

    async def fake_snooze(**kwargs):
        return {
            **task,
            "status": "snoozed",
            "due_at": (datetime.utcnow() + timedelta(minutes=30)).isoformat(),
            "snooze_until": (datetime.utcnow() + timedelta(minutes=30)).isoformat(),
            "user_id": kwargs["user_id"],
            "snooze_minutes": kwargs["minutes"],
        }

    monkeypatch.setattr("app.tools.caretask_tool.svc.resolve_task_ref", fake_resolve)
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
    assert snooze.data["snooze_minutes"] == 30
    assert snooze.data["snooze_minutes"] is not None


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
    from app.tools import registry as reg_mod
    from app.tools.registry import get_tool_registry, list_tool_schemas

    reg_mod._TOOLS = None
    reg = get_tool_registry()
    assert "caretask" in reg
    assert "contact" in reg
    assert "memory" in reg
    names = {s["name"] for s in list_tool_schemas()}
    assert "caretask" in names
    assert "contact" in names
    assert "memory" in names


@pytest.mark.asyncio
async def test_tool_bridge_requires_token_in_production(monkeypatch):
    from fastapi import HTTPException

    from app.api import tool_execute as te

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TOOL_BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("REQUIRE_TOOL_BRIDGE_TOKEN", raising=False)

    with pytest.raises(HTTPException) as exc:
        await te.tool_execute(
            te.ToolExecuteRequest(tool_name="caretask", params={"action": "list"}),
            authorization=None,
            x_tool_bridge_token=None,
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_tool_bridge_accepts_token_header(monkeypatch):
    from app.api import tool_execute as te

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TOOL_BRIDGE_TOKEN", "bridge-secret")

    recorded: list[dict] = []

    class _FakeTrace:
        async def record_tool_call(self, **kwargs):
            recorded.append(kwargs)

    monkeypatch.setattr(
        "app.observability.trace_service.TraceService",
        _FakeTrace,
    )

    resp = await te.tool_execute(
        te.ToolExecuteRequest(
            tool_name="caretask",
            params={"action": "list"},
            trace_id="tr-bridge-1",
        ),
        authorization=None,
        x_tool_bridge_token="bridge-secret",
    )
    assert resp.status == "failed"
    assert resp.data and resp.data.get("reason") == "missing_user"
    assert recorded and recorded[0]["trace_id"] == "tr-bridge-1"
    assert recorded[0]["tool_name"] == "caretask"
