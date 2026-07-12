import asyncio
from datetime import datetime
from types import SimpleNamespace
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


def test_ledger_terminal_fresh_stale_and_conflict_replay_states():
    from app.tools.caretask_batch_executor import _replay_snapshot

    now = datetime(2026, 7, 12, 4, 0)
    receipts = [
        {"index": 0, "action": "list", "status": "completed"},
        {"index": 1, "action": "snooze", "status": "planned"},
        {"index": 2, "action": "complete", "status": "planned"},
    ]
    terminal = {"status": "failed", "receipts": receipts}
    replay, transition = _replay_snapshot(
        status="failed", existing_hash="hash", payload=terminal,
        request_hash="hash", receipts=receipts, now=now,
    )
    assert replay == terminal
    assert transition is None

    fresh, transition = _replay_snapshot(
        status="running", existing_hash="hash",
        payload={"heartbeat_at": now.isoformat(), "receipts": receipts},
        request_hash="hash", receipts=receipts, now=now,
    )
    assert fresh["status"] == "in_progress"
    assert transition is None

    stale, transition = _replay_snapshot(
        status="running", existing_hash="hash",
        payload={"heartbeat_at": datetime(2026, 7, 12, 3, 58).isoformat(), "receipts": receipts},
        request_hash="hash", receipts=receipts, now=now,
    )
    assert transition == "interrupted"
    assert [item["status"] for item in stale["receipts"]] == [
        "completed", "failed", "unattempted"
    ]

    conflict, transition = _replay_snapshot(
        status="completed", existing_hash="old", payload=terminal,
        request_hash="new", receipts=receipts, now=now,
    )
    assert conflict["reason"] == "idempotency_conflict"
    assert transition is None

    all_done = [{"index": 0, "action": "complete", "status": "completed"}]
    recovered, transition = _replay_snapshot(
        status="running", existing_hash="hash",
        payload={"heartbeat_at": datetime(2026, 7, 12, 3, 58).isoformat(), "receipts": all_done},
        request_hash="hash", receipts=all_done, now=now,
    )
    assert recovered["status"] == "completed"
    assert transition == "completed"


def test_ledger_write_requires_owner_hash_and_active_state():
    from app.tools.caretask_batch_executor import _verify_ledger

    record = SimpleNamespace(
        request_hash="hash",
        status="running",
        response_json={"owner": "owner"},
    )
    _verify_ledger(record, owner="owner", request_hash="hash")
    with pytest.raises(RuntimeError, match="owner"):
        _verify_ledger(record, owner="other", request_hash="hash")
    with pytest.raises(RuntimeError, match="idempotency_conflict"):
        _verify_ledger(record, owner="owner", request_hash="other")
    record.status = "completed"
    with pytest.raises(RuntimeError, match="not_active"):
        _verify_ledger(record, owner="owner", request_hash="hash")
    with pytest.raises(RuntimeError, match="batch_ledger_not_found"):
        _verify_ledger(None, owner="owner", request_hash="hash")


@pytest.mark.asyncio
async def test_transaction_failure_commits_neither_domain_nor_receipt(monkeypatch):
    from app.tools import caretask_batch_executor as executor

    ledger = SimpleNamespace(
        request_hash="hash",
        status="running",
        response_json={"owner": "owner"},
    )
    row = SimpleNamespace(
        status="pending", reminder_id=None, version=1, due_at=None,
        snooze_until=None, completed_at=None, updated_at=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=ledger)
    db.flush = AsyncMock(side_effect=RuntimeError("write_failed"))
    db.commit = AsyncMock()

    class SessionContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.db.session.async_session", lambda: SessionContext())
    monkeypatch.setattr(executor.svc, "_get_versioned_task_for_update", AsyncMock(return_value=row))
    receipts = [{"index": 0, "action": "complete", "status": "planned"}]
    with pytest.raises(RuntimeError, match="write_failed"):
        await executor._apply_action_transaction(
            record_id="ledger", user_id="user-1",
            action={"index": 0, "action": "complete", "task_id": "task", "expected_version": 1},
            receipts=receipts, now=datetime(2026, 7, 12, 4, 0),
            owner="owner", request_hash="hash",
        )
    db.commit.assert_not_awaited()
    assert receipts[0]["status"] == "planned"


@pytest.mark.asyncio
async def test_preflight_preserves_canonical_create_reuse(monkeypatch):
    from app.tools import caretask_batch_executor as executor

    monkeypatch.setattr(
        executor.svc,
        "snapshot_care_tasks",
        AsyncMock(return_value=[{
            "id": "task-1", "title": "吃降压药", "task_type": "medication",
            "status": "pending", "version": 4,
        }]),
    )
    actions, reason = await executor._preflight(
        "user-1",
        "每天晚上8点提醒我吃降压药 然后看看今天有哪些任务",
        datetime(2026, 7, 12, 4, 0),
    )
    assert reason is None
    assert actions[0]["reuse_task_id"] == "task-1"
    assert actions[0]["expected_version"] == 4


def test_action_specific_display_includes_titles():
    from app.tools.caretask_batch_executor import _display

    text = _display([
        {"index": 0, "action": "list", "status": "completed", "result": {"titles": ["吃降压药"]}},
        {"index": 1, "action": "complete", "status": "completed", "result": {"title": "复诊"}},
    ])
    assert "吃降压药" in text
    assert "复诊" in text


@pytest.mark.asyncio
async def test_stale_version_marks_current_failed_and_later_unattempted(monkeypatch):
    from app.tools import caretask_batch_executor as executor

    actions = [
        {"index": 0, "action": "complete", "task_id": "task-1", "expected_version": 1},
        {"index": 1, "action": "cancel", "task_id": "task-2", "expected_version": 1},
    ]
    monkeypatch.setattr(executor, "_preflight", AsyncMock(return_value=(actions, None)))
    monkeypatch.setattr(executor, "_lookup_replay", AsyncMock(return_value=None))
    monkeypatch.setattr(executor, "_claim", AsyncMock(return_value=("ledger", "owner", None)))
    monkeypatch.setattr(
        executor,
        "_apply_action_transaction",
        AsyncMock(side_effect=executor.svc.StaleCareTaskVersionError(expected_version=1, current_version=2)),
    )
    save = AsyncMock(side_effect=lambda _id, status, receipts, **kwargs: {
        "status": status, "receipts": receipts
    })
    monkeypatch.setattr(executor, "_save", save)

    result = await executor.execute_caretask_batch(
        user_id="user-1", query="完成任务 然后取消任务", idempotency_key="batch-stale"
    )
    assert result.status == "failed"
    assert [item["status"] for item in result.data["receipts"]] == ["failed", "unattempted"]


@pytest.mark.asyncio
async def test_sequential_exact_create_resolves_reuse_to_created_receipt(monkeypatch):
    from app.tools import caretask_batch_executor as executor

    actions = [
        {"index": 0, "action": "create", "title": "吃降压药", "task_type": "medication", "due_at": None, "query": "记下吃降压药"},
        {"index": 1, "action": "create", "title": "吃降压药", "task_type": "medication", "due_at": None, "query": "再记下吃降压药", "reuse_task_id": "planned:0", "ref_index": 0, "expected_version": 1},
    ]
    monkeypatch.setattr(executor, "_preflight", AsyncMock(return_value=(actions, None)))
    monkeypatch.setattr(executor, "_lookup_replay", AsyncMock(return_value=None))
    monkeypatch.setattr(executor, "_claim", AsyncMock(return_value=("ledger", "owner", None)))
    seen = []

    async def apply(**kwargs):
        action = kwargs["action"]
        seen.append(action)
        result = {"id": "real-task", "title": "吃降压药", "version": 1}
        if action.get("reuse_task_id"):
            result["_action"] = "caretask_reuse"
        kwargs["receipts"][action["index"]] = {
            **kwargs["receipts"][action["index"]], "status": "completed", "result": result,
        }

    monkeypatch.setattr(executor, "_apply_action_transaction", apply)
    monkeypatch.setattr(executor, "_save", AsyncMock(return_value={"status": "completed", "receipts": []}))
    await executor.execute_caretask_batch(
        user_id="user-1", query="记下吃降压药 再记下吃降压药", idempotency_key="dup"
    )
    assert seen[1]["reuse_task_id"] == "real-task"
    assert sum(not item.get("reuse_task_id") for item in seen) == 1


@pytest.mark.asyncio
async def test_today_list_excludes_future_task_without_refresh_write(monkeypatch):
    from app.tools import caretask_batch_executor as executor

    now = datetime(2026, 7, 12, 4, 0)
    snapshot = AsyncMock(return_value=[
        {"id": "today", "title": "今天吃药", "status": "pending", "due_at": "2026-07-12T12:00:00"},
        {"id": "future", "title": "明天复诊", "status": "pending", "due_at": "2026-07-13T12:00:00"},
    ])
    monkeypatch.setattr(executor.svc, "snapshot_care_tasks", snapshot)
    visible = executor._filter_list_snapshot(
        await snapshot(user_id="user-1", now=now), scope="today", now=now
    )
    assert [item["id"] for item in visible] == ["today"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ledger_status", "tool_status"),
    [("completed", "success"), ("failed", "failed"), ("in_progress", "in_progress")],
)
async def test_terminal_and_fresh_replay_never_executes_actions(
    monkeypatch, ledger_status, tool_status
):
    from app.tools import caretask_batch_executor as executor

    cached = {
        "status": ledger_status,
        "receipts": [{"index": 0, "action": "complete", "status": "completed"}],
    }
    preflight = AsyncMock()
    claim = AsyncMock()
    monkeypatch.setattr(executor, "_preflight", preflight)
    monkeypatch.setattr(executor, "_lookup_replay", AsyncMock(return_value=cached))
    monkeypatch.setattr(executor, "_claim", claim)
    apply_action = AsyncMock()
    save = AsyncMock()
    monkeypatch.setattr(executor, "_apply_action_transaction", apply_action)
    monkeypatch.setattr(executor, "_save", save)

    result = await executor.execute_caretask_batch(
        user_id="user-1", query="完成任务 然后看看任务", idempotency_key="replay"
    )
    assert result.status == tool_status
    assert result.data["receipts"] == cached["receipts"]
    apply_action.assert_not_awaited()
    save.assert_not_awaited()
    preflight.assert_not_awaited()
    claim.assert_not_awaited()


def test_request_hash_is_stable_for_normalized_raw_query_and_not_plan_state():
    from app.tools.caretask_batch_executor import _stable_request_hash

    assert _stable_request_hash("每天晚上8点提醒我吃药  然后看看任务") == _stable_request_hash(
        "每天晚上8点提醒我吃药 然后看看任务"
    )
    assert _stable_request_hash("每天晚上8点提醒我吃药") != _stable_request_hash(
        "每天晚上9点提醒我吃药"
    )


@pytest.mark.asyncio
async def test_different_query_same_key_conflicts_before_preflight(monkeypatch):
    from app.tools import caretask_batch_executor as executor

    conflict = {"status": "failed", "reason": "idempotency_conflict", "receipts": []}
    lookup = AsyncMock(return_value=conflict)
    preflight = AsyncMock()
    monkeypatch.setattr(executor, "_lookup_replay", lookup)
    monkeypatch.setattr(executor, "_preflight", preflight)

    result = await executor.execute_caretask_batch(
        user_id="user-1", query="完成复诊 然后看看任务", idempotency_key="same-key"
    )
    assert result.status == "failed"
    assert result.data["reason"] == "idempotency_conflict"
    preflight.assert_not_awaited()


@pytest.mark.asyncio
async def test_ambiguous_cached_replay_keeps_clarification_semantics(monkeypatch):
    from app.tools import caretask_batch_executor as executor

    cached = {
        "status": "completed",
        "receipts": [{
            "index": 0, "action": "clarify", "status": "needs_clarification",
            "reason": "ambiguous_task_ref",
        }],
    }
    preflight = AsyncMock()
    monkeypatch.setattr(executor, "_lookup_replay", AsyncMock(return_value=cached))
    monkeypatch.setattr(executor, "_preflight", preflight)

    result = await executor.execute_caretask_batch(
        user_id="user-1", query="取消吃药提醒 然后看看任务", idempotency_key="ambiguous"
    )
    assert result.status == "needs_clarification"
    assert result.data["receipts"] == cached["receipts"]
    preflight.assert_not_awaited()

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
    monkeypatch.setattr(executor, "_lookup_replay", AsyncMock(return_value=None))
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
