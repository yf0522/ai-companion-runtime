import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.tools.caretask_batch import detect_compound_caretask, plan_caretask_batch
from app.tools.caretask_tool import parse_due_at


def test_compound_plan_preserves_source_order():
    query = "先看看今天有哪些任务，然后把降压药推迟30分钟，再完成复诊任务"
    assert detect_compound_caretask(query)
    plan = plan_caretask_batch(query, now=datetime(2026, 7, 12, 4, 0))
    assert [item.action for item in plan.actions] == ["list", "snooze", "complete"]


def test_two_creates_and_cancel_are_all_discovered():
    query = "每天晚上8点提醒我吃降压药，再记一下明天复诊，然后取消吃药提醒"
    plan = plan_caretask_batch(query, now=datetime(2026, 7, 12, 4, 0))
    assert [item.action for item in plan.actions] == ["create", "create", "cancel"]


def test_exact_space_separated_list_snooze_complete_transcript():
    query = "请列出今天的照护任务 把吃降糖药的提醒延后30分钟 降糖药我已经吃过了"
    plan = plan_caretask_batch(query, now=datetime(2026, 7, 12, 4, 0))
    assert [item.action for item in plan.actions] == ["list", "snooze", "complete"]


def test_exact_space_separated_create_create_cancel_transcript():
    query = "每天早上8点提醒我吃降压药 每天晚上8点提醒我吃降糖药 把吃药提醒取消"
    plan = plan_caretask_batch(query, now=datetime(2026, 7, 12, 4, 0))
    assert [item.action for item in plan.actions] == ["create", "create", "cancel"]


def test_single_action_stays_on_legacy_path():
    assert not detect_compound_caretask("提醒我晚上8点吃药")
    assert not detect_compound_caretask("今天完成了哪些任务")


def test_shanghai_wall_clock_is_stored_as_naive_utc():
    due = parse_due_at("每天晚上8点提醒我吃药", now=datetime(2026, 7, 12, 4, 0))
    assert due == datetime(2026, 7, 12, 12, 0)


def test_explicit_passed_today_time_requires_clarification():
    assert parse_due_at("今天晚上8点提醒我吃药", now=datetime(2026, 7, 12, 13, 0)) is None


def test_unqualified_clock_selects_next_occurrence():
    due = parse_due_at("晚上8点提醒我吃药", now=datetime(2026, 7, 12, 13, 0))
    assert due == datetime(2026, 7, 13, 12, 0)


def test_tomorrow_clock_is_tomorrow_even_before_today_clock():
    due = parse_due_at("明天晚上8点提醒我吃药", now=datetime(2026, 7, 12, 4, 0))
    assert due == datetime(2026, 7, 13, 12, 0)


def test_midnight_boundary_uses_shanghai_calendar():
    due = parse_due_at("明天早上8点提醒我吃药", now=datetime(2026, 7, 12, 15, 59))
    assert due == datetime(2026, 7, 13, 0, 0)


def test_invalid_minutes_and_unsupported_dose_mutation_fail_preflight():
    invalid_minutes = plan_caretask_batch("看看任务 然后把吃药提醒延后2000分钟")
    assert invalid_minutes.status == "invalid"
    assert invalid_minutes.reason == "invalid_snooze_minutes"
    unsupported = plan_caretask_batch("看看任务 然后把降压药改成两片")
    assert unsupported.status == "invalid"
    assert unsupported.reason == "unsupported_or_unmatched_cue"


@pytest.mark.asyncio
async def test_pre_cancelled_batch_never_preflights_or_claims(monkeypatch):
    from app.tools import caretask_batch_executor as executor

    preflight = AsyncMock()
    claim = AsyncMock(return_value=("ledger-1", "owner-1", None))
    save = AsyncMock(return_value={"status": "completed", "receipts": []})
    monkeypatch.setattr(executor, "_preflight", preflight)
    monkeypatch.setattr(executor, "_claim", claim)
    monkeypatch.setattr(executor, "_save", save)
    cancelled = asyncio.Event()
    cancelled.set()

    result = await executor.execute_caretask_batch(
        user_id="user-1",
        query="看看任务 然后完成吃药",
        idempotency_key="batch-1",
        cancel_event=cancelled,
    )

    assert result.status == "cancelled"
    preflight.assert_not_awaited()
    claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_two_planned_creates_make_generic_cancel_ambiguous_and_zero_mutation(monkeypatch):
    from app.tools import caretask_batch_executor as executor

    snapshot = AsyncMock(return_value=[])
    claim = AsyncMock(return_value=("ledger-1", "owner-1", None))
    save = AsyncMock(return_value={"status": "completed", "receipts": []})
    apply_action = AsyncMock()
    monkeypatch.setattr(executor.svc, "snapshot_care_tasks", snapshot)
    monkeypatch.setattr(executor, "_claim", claim)
    monkeypatch.setattr(executor, "_save", save)
    monkeypatch.setattr(executor, "_apply_action_transaction", apply_action)

    result = await executor.execute_caretask_batch(
        user_id="user-1",
        query="每天早上8点提醒我吃降压药 每天晚上8点提醒我吃降糖药 把吃药提醒取消",
        idempotency_key="batch-ambiguous",
    )

    assert result.status == "needs_clarification"
    assert result.data["reason"] == "ambiguous_task_ref"
    claim.assert_awaited_once()
    save.assert_awaited_once()
    apply_action.assert_not_awaited()
