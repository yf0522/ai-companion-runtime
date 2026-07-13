from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import alerts, caretasks, contacts, households, traces
from app.api.auth import create_token
from app.memory.lifecycle import (
    build_privacy_safe_family_summary,
    select_owner_memories,
    serialize_memory,
)
from app.tools import caretask_service
from app.tools.caretask_service import task_to_dict


def _auth(user_id: uuid.UUID, *, role: str) -> dict[str, str]:
    token = create_token(str(user_id), f"{role}-contract-test", role=role)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (caretasks.CareTaskCreate, {"title": "服药", "schedule_type": "interval"}),
        (
            caretasks.CareTaskUpdate,
            {"expected_version": 1, "schedule_type": "interval"},
        ),
    ],
)
def test_caretask_schema_rejects_interval_without_advance_semantics(model, payload) -> None:
    with pytest.raises(ValueError, match="schedule_type"):
        model.model_validate(payload)
    assert caretask_service.SUPPORTED_SCHEDULE_TYPES == {"once", "daily", "weekly"}


@pytest.mark.parametrize(
    ("status", "active", "terminal"),
    [
        ("pending", True, False),
        ("due", True, False),
        ("snoozed", True, False),
        ("done", False, True),
        ("missed", False, True),
        ("cancelled", False, True),
    ],
)
def test_caretask_serialization_has_canonical_state_and_schedule(
    status: str,
    active: bool,
    terminal: bool,
) -> None:
    timestamp = datetime(2026, 7, 11, 8, 30)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="晚间服药",
        task_type="medication",
        status=status,
        due_at=timestamp,
        snooze_until=None,
        reminder_id=uuid.uuid4(),
        notes=None,
        created_by="family",
        completed_at=timestamp if status == "done" else None,
        version=3,
        created_at=timestamp,
        updated_at=timestamp,
    )

    payload = task_to_dict(row, schedule_type="daily")

    assert payload["status"] == status
    assert payload["schedule_type"] == "daily"
    assert payload["is_active"] is active
    assert payload["is_terminal"] is terminal
    assert payload["version"] == 3
    assert payload["updated_at"] == timestamp.isoformat()


@pytest.mark.asyncio
async def test_caretask_update_changes_linked_reminder_recurrence(monkeypatch) -> None:
    timestamp = datetime(2026, 7, 11, 8, 30)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="晚间服药",
        task_type="medication",
        status="pending",
        due_at=timestamp,
        snooze_until=None,
        reminder_id=uuid.uuid4(),
        notes=None,
        created_by="family",
        completed_at=None,
        version=2,
        created_at=timestamp,
        updated_at=timestamp,
    )
    reminder = SimpleNamespace(
        schedule_type="daily",
        title=row.title,
        time_of_day=timestamp,
        next_fire_at=timestamp,
        is_active=True,
    )

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, _model, _row_id):
            return reminder

        async def commit(self):
            return None

        async def refresh(self, _row):
            return None

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())
    monkeypatch.setattr(
        caretask_service,
        "_get_versioned_task_for_update",
        AsyncMock(return_value=row),
    )

    payload = await caretask_service.update_care_task(
        user_id=str(row.user_id),
        task_id=str(row.id),
        expected_version=2,
        schedule_type="weekly",
    )

    assert reminder.schedule_type == "weekly"
    assert payload["schedule_type"] == "weekly"
    assert payload["version"] == 3


@pytest.mark.asyncio
async def test_caretask_update_rejects_terminal_history(monkeypatch) -> None:
    row = SimpleNamespace(status="missed")

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())
    monkeypatch.setattr(
        caretask_service,
        "_get_versioned_task_for_update",
        AsyncMock(return_value=row),
    )

    with pytest.raises(caretask_service.CareTaskTransitionError, match="terminal"):
        await caretask_service.update_care_task(
            user_id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            expected_version=1,
            due_at=datetime(2026, 7, 13, 8, 0),
        )


@pytest.mark.asyncio
async def test_caretask_complete_allows_missed_correction(monkeypatch) -> None:
    timestamp = datetime(2026, 7, 11, 8, 30)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="早间服药",
        task_type="medication",
        status="missed",
        due_at=timestamp,
        snooze_until=None,
        reminder_id=None,
        notes=None,
        created_by="elder",
        completed_at=None,
        version=2,
        created_at=timestamp,
        updated_at=timestamp,
    )

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def commit(self):
            return None

        async def refresh(self, _row):
            return None

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())
    monkeypatch.setattr(
        caretask_service,
        "_get_versioned_task_for_update",
        AsyncMock(return_value=row),
    )

    payload = await caretask_service.complete_care_task(
        user_id=str(row.user_id),
        task_id=str(row.id),
        expected_version=2,
    )

    assert payload["status"] == "done"
    assert payload["completed_at"] is not None
    assert payload["version"] == 3


@pytest.mark.asyncio
async def test_caretask_default_list_query_excludes_every_terminal_state(monkeypatch) -> None:
    captured = {}

    class _Result:
        def all(self):
            return []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement):
            captured["statement"] = statement
            return _Result()

        async def commit(self):
            raise AssertionError("an empty list must not commit")

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())

    assert await caretask_service.list_care_tasks(
        user_id=str(uuid.uuid4()),
        include_terminal=False,
        scope="all",
    ) == []

    parameters = captured["statement"].compile().params
    status_values = next(
        value
        for value in parameters.values()
        if isinstance(value, list) and "pending" in value
    )
    assert set(status_values) == {"pending", "due", "snoozed"}
    assert set(status_values).isdisjoint({"done", "missed", "cancelled"})


@pytest.mark.asyncio
async def test_caretask_history_prioritizes_active_then_recent_terminal(monkeypatch) -> None:
    captured = {}

    class _Result:
        def all(self):
            return []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement):
            captured["statement"] = statement
            return _Result()

        async def commit(self):
            raise AssertionError("an empty list must not commit")

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())

    assert await caretask_service.list_care_tasks(
        user_id=str(uuid.uuid4()),
        include_terminal=True,
        limit=100,
        scope="all",
    ) == []

    sql = str(captured["statement"]).upper()
    assert "CASE" in sql
    assert "NULLS FIRST" in sql
    assert "DESC NULLS LAST" in sql


@pytest.mark.asyncio
async def test_caretask_status_filter_isolates_missed_from_active_pagination(monkeypatch) -> None:
    captured = {}

    class _Result:
        def all(self):
            return []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement):
            captured["statement"] = statement
            return _Result()

        async def commit(self):
            raise AssertionError("an empty list must not commit")

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())

    assert await caretask_service.list_care_tasks(
        user_id=str(uuid.uuid4()),
        statuses=["missed"],
        limit=1,
        scope="all",
    ) == []

    list_parameters = [
        value
        for value in captured["statement"].compile().params.values()
        if isinstance(value, list)
    ]
    assert ["missed"] in list_parameters
    assert not any("pending" in values for values in list_parameters)


def test_contact_contracts_keep_contact_point_and_emergency_contact_distinct() -> None:
    timestamp = datetime(2026, 7, 11, 9, 0)
    household_id = uuid.uuid4()
    user_id = uuid.uuid4()
    contact_point_id = uuid.uuid4()
    contact_point = SimpleNamespace(
        id=contact_point_id,
        household_id=household_id,
        user_id=user_id,
        kind="phone",
        label="女儿手机",
        value="13800000000",
        priority=1,
        availability_json={"timezone": "Asia/Shanghai"},
        verification_state="verified",
        status="active",
        revoked_at=None,
        verified_at=timestamp,
        updated_at=timestamp,
    )
    emergency_contact = SimpleNamespace(
        id=uuid.uuid4(),
        household_id=household_id,
        user_id=user_id,
        contact_point_id=contact_point_id,
        name="小李",
        phone="13800000000",
        relation="daughter",
        priority=1,
        availability_json={"timezone": "Asia/Shanghai"},
        notify_on_levels=["critical", "high"],
        verification_state="verified",
        verified_at=timestamp,
        is_active=True,
        revoked_at=None,
        updated_at=timestamp,
    )

    point_payload = contacts._contact_point_json(contact_point)
    emergency_payload = contacts._emergency_contact_json(emergency_contact)

    assert point_payload["resource_type"] == "contact_point"
    assert point_payload["escalation_order"] is None
    assert point_payload["available"] is True
    assert emergency_payload["resource_type"] == "emergency_contact"
    assert emergency_payload["contact_point_id"] == str(contact_point_id)
    assert emergency_payload["status"] == "active"
    assert "escalation_order" not in emergency_payload


def test_owner_memory_contract_exposes_lifecycle_without_hiding_corrections() -> None:
    created_at = datetime(2026, 7, 10, 10, 0)
    updated_at = datetime(2026, 7, 11, 10, 0)
    payload = serialize_memory(
        {
            "id": uuid.uuid4(),
            "content": "我更喜欢上午散步",
            "memory_type": "preference",
            "importance_score": 0.7,
            "purpose": "care_continuity",
            "sensitivity": "general",
            "consent_status": "granted",
            "correction_state": "corrected",
            "deletion_state": "active",
            "embedding_state": "ready",
            "source": "chat",
            "source_trace_id": "trace-memory-1",
            "created_at": created_at,
            "updated_at": updated_at,
        }
    )

    assert payload["status"] == "corrected"
    assert payload["lifecycle_status"] == "corrected"
    assert payload["consent_status"] == "granted"
    assert payload["retrievable"] is True
    assert payload["retention_status"] == "unbounded"
    assert payload["purpose"] == "care_continuity"
    assert payload["created_at"] == created_at.isoformat()
    assert payload["updated_at"] == updated_at.isoformat()


@pytest.mark.asyncio
async def test_owner_memory_query_includes_lifecycle_states_but_only_active_records() -> None:
    captured = {}

    class _Result:
        def fetchall(self):
            return []

    class _Db:
        async def execute(self, statement):
            captured["statement"] = statement
            return _Result()

    result = await select_owner_memories(_Db(), user_id=uuid.uuid4(), limit=500)

    assert result == []
    compiled = captured["statement"].compile()
    parameters = compiled.params
    lifecycle_values = next(
        value
        for value in parameters.values()
        if isinstance(value, list) and "pending" in value
    )
    assert lifecycle_values == ["pending", "granted", "rejected", "legacy_unverified"]
    assert 100 in parameters.values()
    assert "deletion_state" in str(captured["statement"])


def test_expired_memory_remains_owner_visible_but_not_retrievable() -> None:
    payload = serialize_memory(
        {
            "id": uuid.uuid4(),
            "content": "这条记忆已经超过保留期",
            "memory_type": "fact",
            "importance_score": 0.6,
            "purpose": "care_continuity",
            "sensitivity": "general",
            "consent_status": "granted",
            "retention_until": datetime(2020, 1, 1),
            "correction_state": "original",
            "deletion_state": "active",
        }
    )

    assert payload["lifecycle_status"] == "expired"
    assert payload["retention_status"] == "expired"
    assert payload["retrievable"] is False


def test_family_summary_has_range_denominator_trend_and_safe_item_evidence() -> None:
    timestamp = datetime(2026, 7, 11, 11, 0)
    summary = build_privacy_safe_family_summary(
        [
            {
                "id": "task-1",
                "title": "晚间服药",
                "task_type": "medication",
                "status": "done",
                "owner": "family",
                "evidence": {"source": "care_task", "version": 2},
                "evidence_at": timestamp,
                "private_transcript": "this must never be returned",
            },
            {"id": "task-2", "task_type": "appointment", "status": "missed"},
        ],
        range_key="7d",
        previous_care_outcomes=[
            {"id": "old-1", "task_type": "medication", "status": "missed"}
        ],
    )

    assert summary["range"] == "7d"
    assert summary["denominator"] == 2
    assert summary["completion"] == {"completed": 1, "rate": 0.5}
    assert summary["trend"]["previous_rate"] == 0.0
    assert summary["trend"]["direction"] == "up"
    assert summary["items"][0]["title"] == "晚间服药"
    assert summary["items"][0]["owner"] == "family"
    assert summary["items"][0]["evidence_at"] == timestamp.isoformat()
    assert "private_transcript" not in str(summary)


def test_operator_case_contract_exposes_household_evidence_and_transitions() -> None:
    operator_id = uuid.uuid4()
    household_id = uuid.uuid4()
    decision_id = uuid.uuid4()
    outbox_id = uuid.uuid4()
    timestamp = datetime(2026, 7, 11, 12, 0)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        safety_decision_id=decision_id,
        notification_outbox_id=outbox_id,
        status="assigned",
        severity="high",
        owner_id=operator_id,
        summary="疑似诈骗风险",
        resolution=None,
        due_at=timestamp,
        state_version=4,
        created_at=timestamp,
        resolved_at=None,
    )
    decision = SimpleNamespace(
        trace_id="trace-case-1",
        policy_version="risk-rules:v2",
        risk_category="scam_alert",
        action="notify_family",
        confidence=0.9,
        calibration="high",
        evidence_ref="risk-event:1",
    )
    outbox = SimpleNamespace(
        payload_json={},
        state="delivered",
        provider="signed_webhook",
        channel="webhook",
        attempt_count=1,
        last_error=None,
        updated_at=timestamp,
    )

    payload = alerts._operator_case_json(
        row,
        actor_id=operator_id,
        household_id=household_id,
        decision=decision,
        outbox=outbox,
    )

    assert payload["household_id"] == str(household_id)
    assert payload["trace_id"] == "trace-case-1"
    assert payload["ownership_status"] == "owned_by_me"
    assert payload["allowed_transitions"] == ["closed", "resolved"]
    assert payload["can_add_activity"] is True
    assert payload["evidence"]["safety_decision"]["risk_category"] == "scam_alert"
    assert payload["evidence"]["notification_delivery"]["state"] == "delivered"


def test_case_activity_contract_preserves_actor_and_transition_fields() -> None:
    timestamp = datetime(2026, 7, 11, 12, 30)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        case_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        activity_type="state_transition",
        from_status="assigned",
        to_status="resolved",
        payload_json={"actor_type": "operator", "summary": "风险已核实"},
        created_at=timestamp,
    )

    payload = alerts._case_activity_json(row)

    assert payload["actor_type"] == "operator"
    assert payload["from_status"] == "assigned"
    assert payload["to_status"] == "resolved"
    assert payload["summary"] == "风险已核实"


def test_operator_activity_reserves_actor_summary_and_type(monkeypatch) -> None:
    operator_id = uuid.uuid4()
    case_id = uuid.uuid4()
    operator_case = SimpleNamespace(id=case_id, status="assigned", owner_id=operator_id)

    class _Session:
        def __init__(self):
            self.added = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, _model, _id):
            return operator_case

        def add(self, row):
            self.added.append(row)

        async def commit(self):
            return None

        async def refresh(self, _row):
            return None

    session = _Session()
    monkeypatch.setattr("app.db.session.async_session", lambda: session)
    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)

    invalid = client.post(
        f"/api/operator/cases/{case_id}/activities",
        headers=_auth(operator_id, role="operator"),
        json={"activity_type": "system", "summary": "伪造系统记录"},
    )
    assert invalid.status_code == 422

    response = client.post(
        f"/api/operator/cases/{case_id}/activities",
        headers=_auth(operator_id, role="operator"),
        json={
            "activity_type": "operator_note",
            "summary": "已联系家属",
            "metadata": {"actor_type": "system", "summary": "伪造摘要", "channel": "phone"},
        },
    )
    assert response.status_code == 200
    assert response.json()["actor_type"] == "operator"
    assert response.json()["summary"] == "已联系家属"
    assert session.added[0].payload_json == {
        "channel": "phone",
        "summary": "已联系家属",
        "actor_type": "operator",
    }


def test_operator_trace_pagination_groups_before_limit() -> None:
    statement = traces._operator_trace_page_statement(limit=20, offset=10)
    sql = str(statement.compile(compile_kwargs={"literal_binds": True})).upper()
    assert "GROUP BY" in sql
    assert sql.index("GROUP BY") < sql.index("LIMIT")
    total_sql = str(traces._operator_trace_total_statement()).upper()
    assert "COUNT(DISTINCT" in total_sql


def test_family_ack_links_case_activity_without_resolving_case(monkeypatch) -> None:
    elder_id = uuid.uuid4()
    notification_id = uuid.uuid4()
    case_id = uuid.uuid4()
    outbox_id = uuid.uuid4()
    log = SimpleNamespace(
        id=notification_id,
        user_id=elder_id,
        outbox_id=outbox_id,
        safety_decision_id=None,
        trace_id="trace-family-ack",
        risk_level="high",
        risk_category="scam_alert",
        summary="请家属确认",
        webhook_status="delivered",
        created_at=datetime(2026, 7, 11, 13, 0),
    )
    operator_case = SimpleNamespace(
        id=case_id,
        owner_id=uuid.uuid4(),
        status="assigned",
    )
    outbox = SimpleNamespace(
        id=outbox_id,
        state="delivered",
        provider="signed_webhook",
        channel="sms",
        attempt_count=1,
        last_error=None,
    )
    receipt = SimpleNamespace(
        id=uuid.uuid4(),
        event_type="delivered",
        occurred_at=datetime(2026, 7, 11, 13, 1),
        created_at=datetime(2026, 7, 11, 13, 1),
    )

    async def _notification_contexts(_db, logs):
        return {
            str(logs[0].id): {
                "case": operator_case,
                "outbox": outbox,
                "receipts": [receipt],
                "ack_activity": None,
            }
        }

    monkeypatch.setattr(alerts, "_load_notification_contexts", _notification_contexts)

    class _Result:
        def __init__(self, row):
            self.row = row

        def scalar_one_or_none(self):
            return self.row

    class _Session:
        def __init__(self):
            self.results = iter([log, operator_case])
            self.added = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, _statement):
            return _Result(next(self.results))

        def add(self, row):
            self.added.append(row)

        async def commit(self):
            return None

        async def refresh(self, _row):
            return None

    session = _Session()
    monkeypatch.setattr("app.db.session.async_session", lambda: session)

    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    response = TestClient(app).post(
        f"/api/notifications/{notification_id}/ack",
        headers=_auth(elder_id, role="elder"),
    )

    assert response.status_code == 200
    assert response.json()["operator_case_id"] == str(case_id)
    assert response.json()["operator_case_status"] == "assigned"
    assert response.json()["item"]["status"] == "acknowledged"
    assert response.json()["item"]["acknowledged_by"] == str(elder_id)
    assert response.json()["item"]["acknowledged_at"] is not None
    assert response.json()["item"]["delivery_status"] == "delivered"
    assert response.json()["item"]["delivery"]["state"] == "delivered"
    assert response.json()["item"]["receipts"][0]["event_type"] == "delivered"
    assert log.webhook_status == "delivered"
    assert operator_case.status == "assigned"
    assert len(session.added) == 1
    assert session.added[0].activity_type == "notification_acknowledged"
    assert session.added[0].payload_json["actor_type"] == "elder"
    assert session.added[0].payload_json["summary"] == "长者已确认收到并处理该告警"


def test_notification_ack_serializes_first_writer() -> None:
    statement = alerts._notification_ack_statement(uuid.uuid4(), uuid.uuid4())
    assert "FOR UPDATE" in str(statement).upper()


def test_household_readiness_counts_every_canonical_active_task_state() -> None:
    assert set(households.READINESS_ACTIVE_TASK_STATUSES) == {"pending", "due", "snoozed"}


def test_operator_trace_detail_requires_case_relation_and_writes_audit(monkeypatch) -> None:
    operator_id = uuid.uuid4()
    operator_case = SimpleNamespace(
        id=uuid.uuid4(),
        created_at=datetime(2026, 7, 11, 14, 0),
    )
    decision = SimpleNamespace(trace_id="trace-authorized")

    class _Result:
        def all(self):
            return [(operator_case, decision)]

    class _Session:
        def __init__(self):
            self.added = []
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, _statement):
            return _Result()

        def add(self, row):
            self.added.append(row)

        async def commit(self):
            self.committed = True

    session = _Session()
    monkeypatch.setattr("app.db.session.async_session", lambda: session)
    monkeypatch.setattr(
        traces.trace_service,
        "get_trace",
        AsyncMock(return_value={"trace_id": "trace-authorized", "user_id": str(uuid.uuid4())}),
    )

    app = FastAPI()
    app.include_router(traces.router, prefix="/api")
    response = TestClient(app).get(
        "/api/traces/trace-authorized",
        headers=_auth(operator_id, role="operator"),
    )

    assert response.status_code == 200
    assert response.json()["authorization"]["scope"] == "operator_case"
    assert response.json()["authorization"]["audited"] is True
    assert session.committed is True
    assert session.added[0].activity_type == "trace_viewed"
    assert session.added[0].actor_user_id == operator_id


@pytest.mark.parametrize("role", ["elder", "family"])
def test_ownerless_trace_is_forbidden_to_non_operator(monkeypatch, role) -> None:
    actor_id = uuid.uuid4()
    monkeypatch.setattr(
        traces.trace_service,
        "get_trace",
        AsyncMock(return_value={"trace_id": "trace-ownerless", "user_id": None}),
    )
    app = FastAPI()
    app.include_router(traces.router, prefix="/api")

    response = TestClient(app).get(
        "/api/traces/trace-ownerless",
        headers=_auth(actor_id, role=role),
    )

    assert response.status_code == 404


def test_self_owned_trace_is_visible_to_actor(monkeypatch) -> None:
    actor_id = uuid.uuid4()
    monkeypatch.setattr(
        traces.trace_service,
        "get_trace",
        AsyncMock(return_value={"trace_id": "trace-own", "user_id": str(actor_id)}),
    )
    app = FastAPI()
    app.include_router(traces.router, prefix="/api")

    response = TestClient(app).get(
        "/api/traces/trace-own",
        headers=_auth(actor_id, role="elder"),
    )

    assert response.status_code == 200
    assert response.json()["authorization"]["scope"] == "self"


def test_trace_status_does_not_claim_success_when_evidence_is_missing() -> None:
    assert traces._trace_status(None, None) == "unknown"
    assert traces._trace_status(3, 1) == "failed"
    assert traces._trace_status(3, 0) == "completed"


def test_operator_household_discovery_contract(monkeypatch) -> None:
    operator_id = uuid.uuid4()
    household_id = uuid.uuid4()
    discover = AsyncMock(
        return_value=[
            {
                "id": str(household_id),
                "name": "王阿姨家庭",
                "elder_user_id": str(uuid.uuid4()),
                "elder_name": "王阿姨",
                "status": "active",
                "updated_at": "2026-07-11T15:00:00",
                "readiness_href": f"/api/households/{household_id}/readiness",
            }
        ]
    )
    monkeypatch.setattr(households, "_discover_households", discover)

    app = FastAPI()
    app.include_router(households.router, prefix="/api")
    response = TestClient(app).get(
        "/api/households?query=王&limit=20",
        headers=_auth(operator_id, role="operator"),
    )

    assert response.status_code == 200
    assert response.json()["scope"] == "operator_household_discovery"
    assert response.json()["items"][0]["id"] == str(household_id)
    discover.assert_awaited_once_with(query="王", limit=20)


@pytest.mark.asyncio
async def test_household_readiness_returns_owner_action_and_timestamped_evidence(
    monkeypatch,
) -> None:
    household_id = uuid.uuid4()
    elder_id = uuid.uuid4()
    household = SimpleNamespace(id=household_id, elder_user_id=elder_id)
    counts = iter([1, 0, 1, 1, 1, 1])

    class _CountResult:
        def scalar_one(self):
            return next(counts)

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, _model, _row_id):
            return household

        async def execute(self, _statement):
            return _CountResult()

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())
    monkeypatch.setattr(
        "app.runtime.readiness.assess_platform_readiness",
        AsyncMock(return_value={"status": "ready"}),
    )

    payload = await households._household_readiness(
        household_id,
        {"sub": str(uuid.uuid4()), "role": "operator"},
    )

    contact_check = next(
        item for item in payload["checks"] if item["key"] == "verified_contact"
    )
    assert contact_check["status"] == "blocked"
    assert contact_check["owner"] == "家庭管理员"
    assert contact_check["action"] == "添加联系方式并完成验证码验证"
    assert contact_check["evidence"] == {"verified_contact_count": 0}
    assert contact_check["evidence_at"] == payload["updated_at"]


def test_escalation_policy_list_preserves_policy_and_step_semantics(monkeypatch) -> None:
    operator_id = uuid.uuid4()
    household_id = uuid.uuid4()
    policy_id = uuid.uuid4()
    contact_point_id = uuid.uuid4()
    timestamp = datetime(2026, 7, 11, 16, 0)
    policy = SimpleNamespace(
        id=policy_id,
        household_id=household_id,
        name="高风险升级",
        version=2,
        status="active",
        created_at=timestamp,
        updated_at=timestamp,
    )
    step = SimpleNamespace(
        id=uuid.uuid4(),
        policy_id=policy_id,
        step_order=1,
        action="notify_contact",
        contact_point_id=contact_point_id,
        delay_seconds=0,
        config_json={"levels": ["critical"]},
    )

    class _Scalars:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class _Result:
        def __init__(self, rows):
            self.rows = rows

        def scalars(self):
            return _Scalars(self.rows)

    class _Session:
        def __init__(self):
            self.results = iter([[policy], [step]])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, _statement):
            return _Result(next(self.results))

    monkeypatch.setattr(
        households,
        "_authorize_household_read",
        AsyncMock(return_value=SimpleNamespace(id=household_id)),
    )
    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())

    app = FastAPI()
    app.include_router(households.router, prefix="/api")
    response = TestClient(app).get(
        f"/api/households/{household_id}/escalation-policies",
        headers=_auth(operator_id, role="operator"),
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["resource_type"] == "escalation_policy"
    assert item["steps"][0]["resource_type"] == "escalation_step"
    assert item["steps"][0]["contact_point_id"] == str(contact_point_id)
    assert "priority" not in item["steps"][0]
