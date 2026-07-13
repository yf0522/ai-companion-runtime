import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools.caretask_batch import detect_compound_caretask, plan_caretask_batch
from app.tools.caretask_tool import parse_due_at


class _SingleScalarResult:
    def __init__(self, record):
        self._record = record

    def scalar_one_or_none(self):
        return self._record


class _SingleTransaction:
    def __init__(self, state, db):
        self._state = state
        self._db = db
        self._snapshot = None

    async def __aenter__(self):
        self._snapshot = (self._state.record, self._state.snooze_count)
        self._db.in_transaction = True
        return self._db

    async def __aexit__(self, exc_type, _exc, _tb):
        if exc_type is not None:
            self._state.record, self._state.snooze_count = self._snapshot
        self._db.in_transaction = False
        return False


class _SingleSession:
    def __init__(self, state):
        self._state = state
        self.in_transaction = False

    def begin(self):
        return _SingleTransaction(self._state, self)

    async def execute(self, _query):
        return _SingleScalarResult(self._state.record)

    def add(self, record):
        assert self.in_transaction
        record.id = record.id or "single-ledger"
        self._state.record = record

    async def flush(self):
        assert self.in_transaction


class _SingleSessionContext:
    def __init__(self, state):
        self._db = _SingleSession(state)

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *_args):
        return False


def test_compound_plan_preserves_source_order():
    query = "先看看今天有哪些任务，然后把降压药推迟30分钟，再完成复诊任务"
    assert detect_compound_caretask(query)
    plan = plan_caretask_batch(query, now=datetime(2026, 7, 12, 4, 0))
    assert [item.action for item in plan.actions] == ["list", "snooze", "complete"]


def test_two_creates_and_cancel_are_all_discovered():
    query = "每天晚上8点提醒我吃降压药，再记一下明天复诊，然后取消吃药提醒"
    plan = plan_caretask_batch(query, now=datetime(2026, 7, 12, 4, 0))
    assert [item.action for item in plan.actions] == ["create", "create", "cancel"]


@pytest.mark.parametrize(
    "query",
    [
        "请问如何取消吃药提醒，然后怎么完成复诊任务",
        "我只是举例：取消吃药提醒，然后完成复诊任务",
        "不要取消吃药提醒，然后也别完成复诊任务",
        "新闻里说“取消吃药提醒，然后完成复诊",
        "如果需要就取消吃药提醒，然后完成复诊任务",
        "医生让我取消吃药提醒，然后完成复诊任务",
        "是否取消吃药提醒，然后完成复诊任务？",
    ],
)
def test_compound_mutations_require_affirmative_authorization(query):
    assert detect_compound_caretask(query)
    plan = plan_caretask_batch(query)
    assert plan.status == "needs_clarification"
    assert plan.actions == ()


@pytest.mark.parametrize("query", ["完成吃药和取消复诊", "完成吃药并取消复诊"])
def test_bounded_chinese_conjunction_preserves_two_authorized_actions(query):
    plan = plan_caretask_batch(query)
    assert plan.status == "planned"
    assert [item.action for item in plan.actions] == ["complete", "cancel"]
    assert [item.query for item in plan.actions] == ["完成吃药", "取消复诊"]


def test_raw_mutation_cue_cannot_be_silently_dropped():
    plan = plan_caretask_batch("完成吃药取消复诊")
    assert plan.status == "needs_clarification"
    assert plan.reason in {
        "ambiguous_mutation_cues",
        "mutation_not_authorized",
        "unplanned_mutation_cue",
    }
    assert plan.actions == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "请问如何取消吃药提醒，然后怎么完成复诊任务",
        "我只是举例：取消吃药提醒，然后完成复诊任务",
        "不要取消吃药提醒，然后也别完成复诊任务",
        "新闻里说“取消吃药提醒，然后完成复诊",
    ],
)
async def test_unauthorized_compound_turn_has_zero_domain_execution(monkeypatch, query):
    from app.tools import caretask_batch_executor as executor

    monkeypatch.setattr(executor, "_lookup_replay", AsyncMock(return_value=None))
    monkeypatch.setattr(executor, "_claim", AsyncMock(return_value=("ledger", "owner", None)))
    monkeypatch.setattr(
        executor,
        "_save",
        AsyncMock(return_value={"status": "completed", "receipts": []}),
    )
    snapshot = AsyncMock(return_value=[])
    apply_action = AsyncMock()
    monkeypatch.setattr(executor.svc, "snapshot_care_tasks", snapshot)
    monkeypatch.setattr(executor, "_apply_action_transaction", apply_action)

    result = await executor.execute_caretask_batch(
        user_id="user-1", query=query, idempotency_key=f"unsafe-{hash(query)}"
    )

    assert result.status == "needs_clarification"
    snapshot.assert_not_awaited()
    apply_action.assert_not_awaited()


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
async def test_transaction_primitive_preserves_weekly_recurrence():
    import uuid

    from app.db.models import Reminder
    from app.tools import caretask_service as service

    added = []
    db = AsyncMock()

    def add(row):
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()
        added.append(row)

    db.add = add
    db.flush = AsyncMock()
    result = await service.create_or_reuse_care_task_in_transaction(
        db,
        user_id="user-1",
        title="吃降压药",
        task_type="medication",
        due_at=datetime(2026, 7, 13, 0, 0),
        query="每周一早上8点提醒我吃降压药",
        now=datetime(2026, 7, 12, 4, 0),
    )

    reminder = next(row for row in added if isinstance(row, Reminder))
    assert reminder.schedule_type == "weekly"
    assert result["schedule_type"] == "weekly"
    assert not hasattr(db, "commit") or db.commit.await_count == 0


@pytest.mark.asyncio
async def test_transaction_transition_refreshes_due_state_before_completion(monkeypatch):
    from app.tools import caretask_service as service

    now = datetime(2026, 7, 12, 4, 0)
    row = SimpleNamespace(
        id="task-1", user_id="user-1", title="吃药", task_type="medication",
        status="pending", due_at=datetime(2026, 7, 12, 3, 0),
        snooze_until=None, reminder_id=None, notes=None, created_by="chat",
        completed_at=None, version=1, created_at=None, updated_at=None,
    )
    monkeypatch.setattr(
        service, "_get_versioned_task_for_update", AsyncMock(return_value=row)
    )
    refresh = MagicMock(return_value="due")
    monkeypatch.setattr(service, "refresh_status", refresh)
    db = AsyncMock()
    result = await service.transition_care_task_in_transaction(
        db,
        user_id="user-1",
        task_id="task-1",
        expected_version=1,
        transition="complete",
        now=now,
    )

    assert result["status"] == "done"
    assert row.completed_at == now
    refresh.assert_called_once_with(
        "pending", datetime(2026, 7, 12, 3, 0), None, now
    )
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_transaction_reuse_without_state_change_does_not_increment_version(
    monkeypatch,
):
    from app.tools import caretask_service as service

    now = datetime(2026, 7, 12, 4, 0)
    due = datetime(2026, 7, 12, 12, 0)
    row = SimpleNamespace(
        id="task-1", user_id="user-1", title="吃降压药", task_type="medication",
        status="pending", due_at=due, snooze_until=None, reminder_id="reminder-1",
        notes=None, created_by="chat", completed_at=None, version=4,
        created_at=None, updated_at=None,
    )
    reminder = SimpleNamespace(
        schedule_type="daily", time_of_day=due, next_fire_at=due, is_active=True
    )
    monkeypatch.setattr(
        service, "_get_versioned_task_for_update", AsyncMock(return_value=row)
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=reminder)

    result = await service.create_or_reuse_care_task_in_transaction(
        db,
        user_id="user-1",
        title="吃降压药",
        task_type="medication",
        due_at=due,
        query="每天晚上8点提醒我吃降压药",
        now=now,
        reuse_task_id="task-1",
        expected_version=4,
    )

    assert result["version"] == 4
    assert row.updated_at is None
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_audit_fields_survive_running_terminal_and_cached_replay(monkeypatch):
    from app.tools import caretask_batch_executor as executor

    ledger = SimpleNamespace(
        request_hash="request-hash",
        status="claimed",
        response_json={
            "status": "claimed",
            "owner": "owner",
            "plan_hash": "original-plan-hash",
            "frozen_at": "2026-07-12T04:00:00",
            "receipts": [{"index": 0, "action": "list", "status": "planned"}],
        },
        updated_at=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=ledger)
    db.commit = AsyncMock()

    class SessionContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.db.session.async_session", lambda: SessionContext())
    monkeypatch.setattr(executor.svc, "snapshot_care_tasks", AsyncMock(return_value=[]))
    receipts = [{"index": 0, "action": "list", "status": "planned"}]

    await executor._apply_action_transaction(
        record_id="ledger", user_id="user-1",
        action={"index": 0, "action": "list", "scope": "all"},
        receipts=receipts, now=datetime(2026, 7, 12, 4, 0),
        owner="owner", request_hash="request-hash",
    )
    assert ledger.response_json["plan_hash"] == "original-plan-hash"
    assert ledger.response_json["frozen_at"] == "2026-07-12T04:00:00"

    terminal = await executor._save(
        "ledger", "completed", receipts,
        owner="owner", request_hash="request-hash",
    )
    replay = executor._result_from_replay(terminal)
    assert replay.data["plan_hash"] == "original-plan-hash"
    assert replay.data["frozen_at"] == "2026-07-12T04:00:00"


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


@pytest.mark.asyncio
async def test_reuse_with_schedule_update_advances_simulated_version_before_transition(
    monkeypatch,
):
    from app.tools import caretask_batch_executor as executor

    old_due = datetime(2026, 7, 12, 11, 0)
    monkeypatch.setattr(
        executor.svc,
        "snapshot_care_tasks",
        AsyncMock(return_value=[{
            "id": "task-1", "title": "吃降压药", "task_type": "medication",
            "status": "pending", "version": 4, "due_at": old_due.isoformat(),
            "reminder_id": "reminder-1", "schedule_type": "daily",
            "_reminder_time_of_day": old_due,
            "_reminder_next_fire_at": old_due,
            "_reminder_is_active": True,
        }]),
    )

    actions, reason = await executor._preflight(
        "user-1",
        "每天晚上8点提醒我吃降压药 然后完成降压药",
        datetime(2026, 7, 12, 4, 0),
    )

    assert reason is None
    assert actions[0]["expected_version"] == 4
    assert actions[1]["task_id"] == "task-1"
    assert actions[1]["expected_version"] == 5


@pytest.mark.asyncio
async def test_reuse_without_state_change_preserves_version_before_transition(monkeypatch):
    from app.tools import caretask_batch_executor as executor

    due = datetime(2026, 7, 12, 12, 0)
    monkeypatch.setattr(
        executor.svc,
        "snapshot_care_tasks",
        AsyncMock(return_value=[{
            "id": "task-1", "title": "吃降压药", "task_type": "medication",
            "status": "pending", "version": 4, "due_at": due.isoformat(),
            "reminder_id": "reminder-1", "schedule_type": "daily",
            "_reminder_time_of_day": due,
            "_reminder_next_fire_at": due,
            "_reminder_is_active": True,
        }]),
    )

    actions, reason = await executor._preflight(
        "user-1",
        "每天晚上8点提醒我吃降压药 然后完成降压药",
        datetime(2026, 7, 12, 4, 0),
    )

    assert reason is None
    assert actions[0]["expected_version"] == 4
    assert actions[1]["expected_version"] == 4


@pytest.mark.asyncio
async def test_planned_task_uses_latest_prior_action_receipt_after_reuse_update(
    monkeypatch,
):
    from app.tools import caretask_batch_executor as executor

    monkeypatch.setattr(executor.svc, "snapshot_care_tasks", AsyncMock(return_value=[]))

    actions, reason = await executor._preflight(
        "user-1",
        "明天早上8点提醒我吃降压药 然后明天晚上8点提醒我吃降压药 然后完成降压药",
        datetime(2026, 7, 12, 4, 0),
    )

    assert reason is None
    assert [action.get("ref_index") for action in actions] == [None, 0, 1]
    assert [action.get("expected_version") for action in actions] == [None, 1, 2]


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
async def test_external_version_change_rejects_reuse_before_later_transition(monkeypatch):
    from app.tools import caretask_batch_executor as executor

    actions = [
        {
            "index": 0, "action": "create", "title": "吃降压药",
            "task_type": "medication", "due_at": datetime(2026, 7, 12, 12, 0),
            "query": "每天晚上8点提醒我吃降压药", "reuse_task_id": "task-1",
            "expected_version": 4,
        },
        {
            "index": 1, "action": "complete", "task_id": "task-1",
            "expected_version": 5,
        },
    ]
    monkeypatch.setattr(executor, "_preflight", AsyncMock(return_value=(actions, None)))
    monkeypatch.setattr(executor, "_lookup_replay", AsyncMock(return_value=None))
    monkeypatch.setattr(executor, "_claim", AsyncMock(return_value=("ledger", "owner", None)))
    apply = AsyncMock(
        side_effect=executor.svc.StaleCareTaskVersionError(
            expected_version=4, current_version=5
        )
    )
    monkeypatch.setattr(executor, "_apply_action_transaction", apply)
    monkeypatch.setattr(
        executor,
        "_save",
        AsyncMock(side_effect=lambda _id, status, receipts, **kwargs: {
            "status": status, "receipts": receipts,
        }),
    )

    result = await executor.execute_caretask_batch(
        user_id="user-1", query="更新后完成", idempotency_key="stale-reuse"
    )

    assert result.status == "failed"
    assert [item["status"] for item in result.data["receipts"]] == [
        "failed", "unattempted",
    ]
    apply.assert_awaited_once()


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
async def test_single_mutation_replays_same_hash_and_conflicts_on_different_hash(monkeypatch):
    from app.tools import caretask_batch_executor as executor
    from app.tools.base import ToolResult

    state = SimpleNamespace(record=None, snooze_count=0)
    monkeypatch.setattr(
        "app.db.session.async_session", lambda: _SingleSessionContext(state)
    )

    async def transition(db, **kwargs):
        assert db.in_transaction
        state.snooze_count += 1
        return {
            "id": kwargs["task_id"],
            "title": "吃降压药",
            "status": "snoozed",
            "snooze_minutes": kwargs["minutes"],
        }

    monkeypatch.setattr(
        executor.svc, "transition_care_task_in_transaction", transition
    )

    def render(row):
        return ToolResult(
            tool_name="caretask",
            status="success",
            display_text="好的，我30分钟后再提醒您吃降压药",
            data={
                "action": "caretask_snooze",
                "task": row,
                "snooze_minutes": 30,
            },
        )

    kwargs = {
        "user_id": "11111111-1111-4111-8111-111111111111",
        "idempotency_key": "same-key",
        "request_payload": {"action": "snooze", "query": "把降压药延后30分钟"},
        "mutation": {
            "action": "snooze",
            "task_id": "22222222-2222-4222-8222-222222222222",
            "expected_version": 1,
            "minutes": 30,
        },
        "render": render,
    }
    first = await executor.execute_single_caretask_mutation(**kwargs)
    replay = await executor.execute_single_caretask_mutation(**kwargs)
    conflict = await executor.execute_single_caretask_mutation(
        **{
            **kwargs,
            "request_payload": {"action": "snooze", "query": "把降压药延后60分钟"},
        }
    )

    assert first.display_text == replay.display_text
    assert replay.data == first.data
    assert state.snooze_count == 1
    assert conflict.status == "failed"
    assert conflict.data["reason"] == "idempotency_conflict"


@pytest.mark.asyncio
async def test_single_mutation_failure_rolls_back_domain_and_idempotency_together(monkeypatch):
    from app.tools import caretask_batch_executor as executor
    from app.tools.base import ToolResult

    state = SimpleNamespace(record=None, snooze_count=0)
    monkeypatch.setattr(
        "app.db.session.async_session", lambda: _SingleSessionContext(state)
    )

    async def fail_after_mutation(db, **_kwargs):
        assert db.in_transaction
        state.snooze_count += 1
        raise RuntimeError("commit_path_failed")

    monkeypatch.setattr(
        executor.svc, "transition_care_task_in_transaction", fail_after_mutation
    )

    with pytest.raises(RuntimeError, match="commit_path_failed"):
        await executor.execute_single_caretask_mutation(
            user_id="11111111-1111-4111-8111-111111111111",
            idempotency_key="atomic-key",
            request_payload={"action": "snooze", "query": "延后30分钟"},
            mutation={
                "action": "snooze",
                "task_id": "22222222-2222-4222-8222-222222222222",
                "expected_version": 1,
                "minutes": 30,
            },
            render=lambda row: ToolResult(
                tool_name="caretask", status="success", data={"task": row}
            ),
        )

    assert state.snooze_count == 0
    assert state.record is None


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
