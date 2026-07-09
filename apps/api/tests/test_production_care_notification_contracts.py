from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api import alerts, caretasks
from app.api.auth import create_token
from app.tools import caretask_service as caretask_svc
from app.main import app as main_app
from app.workers import reminder_scheduler
from app.workers.notification_outbox_worker import (
    ClaimedOutbox,
    ProviderResult,
    SandboxNotificationProvider,
    UnconfiguredNotificationProvider,
)


def _auth(user_id: str, role: str = "elder") -> dict[str, str]:
    token = create_token(user_id, f"{role}-user", role=role)
    return {"Authorization": f"Bearer {token}"}


def test_caretask_route_registered_on_main_app() -> None:
    client = TestClient(main_app)
    assert client.get("/api/care-tasks").status_code == 401
    assert client.post(f"/api/care-tasks/{uuid.uuid4()}/complete").status_code == 401


def test_caretask_create_requires_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    elder_id = uuid.uuid4()

    async def fake_elder(_user: dict, *, permission: str) -> uuid.UUID:
        assert permission == "manage_reminders"
        return elder_id

    monkeypatch.setattr(caretasks, "_get_managed_elder_id", fake_elder)

    app = FastAPI()
    app.include_router(caretasks.router, prefix="/api")
    client = TestClient(app)

    res = client.post(
        "/api/care-tasks",
        json={"title": "吃降压药", "task_type": "medication"},
        headers=_auth(str(elder_id)),
    )
    assert res.status_code == 428


def test_caretask_create_idempotent_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    elder_id = uuid.uuid4()
    task_id = uuid.uuid4()
    calls = {"create": 0}
    stored: dict[str, object] = {}
    claim_id = uuid.uuid4()

    async def fake_elder(_user: dict, *, permission: str) -> uuid.UUID:
        return elder_id

    async def fake_claim(*, user_id, key, operation, request_hash):
        if stored:
            response = dict(stored["response"])
            response["idempotent_replay"] = True
            return caretasks.IdempotencyClaim(
                state=caretasks.IdempotencyClaimState.REPLAY,
                response=response,
            )
        return caretasks.IdempotencyClaim(
            state=caretasks.IdempotencyClaimState.WON,
            record_id=claim_id,
        )

    async def fake_finish(**kwargs):
        stored["response"] = kwargs["response"]

    async def fake_create_care_task(**kwargs):
        calls["create"] += 1
        return {
            "id": str(task_id),
            "user_id": str(elder_id),
            "title": kwargs["title"],
            "status": "pending",
            "version": 1,
        }

    monkeypatch.setattr(caretasks, "_get_managed_elder_id", fake_elder)
    monkeypatch.setattr(caretasks, "_claim_idempotency", fake_claim)
    monkeypatch.setattr(caretasks, "_finish_idempotency", fake_finish)
    monkeypatch.setattr(caretasks.svc, "create_care_task", fake_create_care_task)

    app = FastAPI()
    app.include_router(caretasks.router, prefix="/api")
    client = TestClient(app)
    headers = {**_auth(str(elder_id)), "Idempotency-Key": "create-med-1"}
    body = {"title": "吃降压药", "task_type": "medication"}

    first = client.post("/api/care-tasks", json=body, headers=headers)
    second = client.post("/api/care-tasks", json=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert calls["create"] == 1


def test_caretask_complete_rejects_stale_version(monkeypatch: pytest.MonkeyPatch) -> None:
    elder_id = uuid.uuid4()
    task_id = uuid.uuid4()

    async def fake_elder(_user: dict, *, permission: str) -> uuid.UUID:
        return elder_id

    async def fake_claim(**kwargs):
        return caretasks.IdempotencyClaim(
            state=caretasks.IdempotencyClaimState.WON,
            record_id=uuid.uuid4(),
        )

    async def fake_finish(**kwargs):
        return None

    async def fake_complete_care_task(**kwargs):
        raise caretask_svc.StaleCareTaskVersionError(
            expected_version=kwargs["expected_version"],
            current_version=2,
        )

    monkeypatch.setattr(caretasks, "_get_managed_elder_id", fake_elder)
    monkeypatch.setattr(caretasks, "_claim_idempotency", fake_claim)
    monkeypatch.setattr(caretasks, "_finish_idempotency", fake_finish)
    monkeypatch.setattr(caretasks.svc, "complete_care_task", fake_complete_care_task)

    app = FastAPI()
    app.include_router(caretasks.router, prefix="/api")
    client = TestClient(app)
    res = client.post(
        f"/api/care-tasks/{task_id}/complete",
        json={"expected_version": 1},
        headers={**_auth(str(elder_id)), "Idempotency-Key": "complete-1"},
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "stale_version"


@pytest.mark.asyncio
async def test_caretask_idempotency_concurrent_claim_executes_business_mutation_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_id = uuid.uuid4()
    lock = asyncio.Lock()
    state = {"claimed": False, "business_calls": 0}

    async def fake_claim(**kwargs):
        async with lock:
            if state["claimed"]:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "idempotency_in_progress", "operation": kwargs["operation"]},
                )
            state["claimed"] = True
            await asyncio.sleep(0)
            return caretasks.IdempotencyClaim(
                state=caretasks.IdempotencyClaimState.WON,
                record_id=claim_id,
            )

    async def fake_finish(**kwargs):
        return None

    async def business_action(_clean_key: str) -> dict[str, object]:
        state["business_calls"] += 1
        await asyncio.sleep(0.01)
        return {"id": str(uuid.uuid4())}

    monkeypatch.setattr(caretasks, "_claim_idempotency", fake_claim)
    monkeypatch.setattr(caretasks, "_finish_idempotency", fake_finish)

    first, second = await asyncio.gather(
        caretasks._run_idempotent(
            actor_id=uuid.uuid4(),
            key="same-key",
            operation="caretask:create",
            payload={"title": "吃药"},
            action=business_action,
        ),
        caretasks._run_idempotent(
            actor_id=uuid.uuid4(),
            key="same-key",
            operation="caretask:create",
            payload={"title": "吃药"},
            action=business_action,
        ),
        return_exceptions=True,
    )

    assert state["business_calls"] == 1
    assert isinstance(first, dict) or isinstance(second, dict)
    conflict = second if isinstance(first, dict) else first
    assert isinstance(conflict, HTTPException)
    assert conflict.status_code == 409
    assert conflict.detail["code"] == "idempotency_in_progress"


@pytest.mark.asyncio
async def test_caretask_version_lock_uses_postgresql_for_update_and_version_predicate() -> None:
    task_id = uuid.uuid4()
    user_id = uuid.uuid4()
    captured: list[object] = []

    class _Result:
        def scalar_one_or_none(self):
            return SimpleNamespace(id=task_id, user_id=user_id, version=3)

    class _Session:
        async def execute(self, stmt):
            captured.append(stmt)
            return _Result()

    row = await caretask_svc._get_versioned_task_for_update(
        _Session(),
        user_id,
        str(task_id),
        3,
    )

    compiled = str(captured[0].compile(dialect=postgresql.dialect()))
    assert row.version == 3
    assert "FOR UPDATE" in compiled
    assert "care_tasks.version" in compiled
    assert "care_tasks.id" in compiled
    assert "care_tasks.user_id" in compiled


@pytest.mark.asyncio
async def test_caretask_version_lock_stale_row_returns_current_version() -> None:
    task_id = uuid.uuid4()
    user_id = uuid.uuid4()

    class _Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class _Session:
        def __init__(self):
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            if self.calls == 1:
                return _Result(None)
            return _Result(4)

    session = _Session()
    with pytest.raises(caretask_svc.StaleCareTaskVersionError) as exc:
        await caretask_svc._get_versioned_task_for_update(session, user_id, str(task_id), 3)

    assert session.calls == 2
    assert exc.value.expected_version == 3
    assert exc.value.current_version == 4


def test_reminder_attempt_idempotency_key_and_retry_state() -> None:
    rid = uuid.uuid4()
    due = datetime(2026, 7, 10, 8, 0, 0, 123)

    key1 = reminder_scheduler.build_attempt_idempotency_key(rid, due, 1)
    key2 = reminder_scheduler.build_attempt_idempotency_key(rid, due.replace(microsecond=999), 1)
    assert key1 == key2

    now = datetime(2026, 7, 10, 8, 1, 0)
    retry = reminder_scheduler.next_delivery_state(delivered=False, attempt_number=2, now=now)
    terminal = reminder_scheduler.next_delivery_state(delivered=False, attempt_number=3, now=now)
    sent = reminder_scheduler.next_delivery_state(delivered=True, attempt_number=1, now=now)

    assert retry["state"] == "retry_scheduled"
    assert retry["next_fire_at"] == now + timedelta(minutes=4)
    assert terminal["state"] == "failed"
    assert terminal["is_terminal_failure"] is True
    assert sent["state"] == "sent"


@pytest.mark.asyncio
async def test_notification_providers_are_deterministic_and_explicit() -> None:
    class _Outbox:
        idempotency_key = "risk-key-1"
        payload_json = {"summary": "疑似诈骗"}

    sandbox = SandboxNotificationProvider()
    first = await sandbox.send(_Outbox())
    second = await sandbox.send(_Outbox())
    assert first.state == "accepted"
    assert first.provider_message_id == second.provider_message_id

    unconfigured = await UnconfiguredNotificationProvider().send(_Outbox())
    assert unconfigured.state == "unconfigured"
    assert unconfigured.permanent is True


def test_safety_escalation_api_uses_transactional_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    elder_id = uuid.uuid4()
    decision_id = uuid.uuid4()
    outbox_id = uuid.uuid4()

    async def fake_elder(_user: dict) -> uuid.UUID:
        return elder_id

    async def fake_pipeline(**kwargs):
        assert kwargs["user_id"] == str(elder_id)
        assert kwargs["risk_category"] == "scam_alert"
        return {
            "status": "persisted",
            "safety_decision_id": str(decision_id),
            "outbox_ids": [str(outbox_id)],
            "case_opened": True,
            "webhook_status": "queued",
        }

    monkeypatch.setattr(alerts, "_get_managed_elder_id", fake_elder)
    monkeypatch.setattr(
        "app.workers.notification_outbox_worker.create_safety_notification_pipeline",
        fake_pipeline,
    )

    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)
    res = client.post(
        "/api/safety/escalations",
        json={
            "risk_level": "high",
            "risk_category": "scam_alert",
            "summary": "疑似诈骗，请确认",
            "trace_id": "tr_safety",
            "policy_version": "risk-rules:2026-07-10",
        },
        headers=_auth(str(elder_id), role="family"),
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["safety_decision_id"] == str(decision_id)
    assert payload["outbox_ids"] == [str(outbox_id)]
    assert payload["case_opened"] is True


def test_operator_case_api_requires_operator_role() -> None:
    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)

    res = client.get("/api/operator/cases", headers=_auth(str(uuid.uuid4()), role="family"))
    assert res.status_code == 403


class _ScalarResult:
    def __init__(self, value: object | None = None, rows: list[object] | None = None) -> None:
        self.value = value
        self.rows = rows or []

    def scalar_one_or_none(self) -> object | None:
        return self.value

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> list[object]:
        return self.rows


class _ReceiptSession:
    def __init__(self, outbox: object, receipts: list[object]) -> None:
        self.outbox = outbox
        self.receipts = receipts
        self.commits = 0

    async def __aenter__(self) -> "_ReceiptSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, _stmt: object) -> _ScalarResult:
        self._execute_calls = getattr(self, "_execute_calls", 0) + 1
        if self._execute_calls == 1:
            return _ScalarResult(value=self.outbox)
        return _ScalarResult(value=self.receipts[-1] if self.receipts else None)

    def add(self, obj: object) -> None:
        self.receipts.append(obj)

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_notification_receipt_duplicate_callback_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers.notification_outbox_worker import record_provider_receipt

    outbox = type("_Outbox", (), {})()
    outbox.id = uuid.uuid4()
    outbox.state = "accepted"
    outbox.provider_message_id = "provider_msg_1"
    receipts: list[object] = []

    sessions = [_ReceiptSession(outbox, receipts), _ReceiptSession(outbox, receipts)]
    monkeypatch.setattr("app.db.session.async_session", lambda: sessions.pop(0))

    first = await record_provider_receipt(
        outbox_id=str(outbox.id),
        event_type="delivered",
        provider_message_id="provider_msg_1",
        payload={"provider_event": "delivered"},
    )
    second = await record_provider_receipt(
        outbox_id=str(outbox.id),
        event_type="delivered",
        provider_message_id="provider_msg_1",
        payload={"provider_event": "delivered"},
    )

    assert first["state"] == "delivered"
    assert second["state"] == "delivered"
    assert len(receipts) == 1


@pytest.mark.asyncio
async def test_notification_receipt_rejects_cross_elder_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers.notification_outbox_worker import record_provider_receipt

    class _MissingSession:
        async def __aenter__(self) -> "_MissingSession":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def execute(self, _stmt: object) -> _ScalarResult:
            return _ScalarResult(value=None)

    monkeypatch.setattr("app.db.session.async_session", lambda: _MissingSession())

    with pytest.raises(LookupError):
        await record_provider_receipt(
            outbox_id=str(uuid.uuid4()),
            event_type="delivered",
            expected_user_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_notification_late_receipt_does_not_regress_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers.notification_outbox_worker import record_provider_receipt

    outbox = type("_Outbox", (), {})()
    outbox.id = uuid.uuid4()
    outbox.state = "delivered"
    outbox.provider_message_id = "provider_msg_2"
    receipts: list[object] = []

    monkeypatch.setattr("app.db.session.async_session", lambda: _ReceiptSession(outbox, receipts))

    result = await record_provider_receipt(
        outbox_id=str(outbox.id),
        event_type="accepted",
        provider_message_id="provider_msg_2",
        payload={"provider_event": "accepted_late"},
    )

    assert result["state"] == "delivered"
    assert outbox.state == "delivered"
    assert len(receipts) == 1


def test_notification_permanent_failure_is_terminal() -> None:
    from app.workers.notification_outbox_worker import _provider_result_update_values

    now = datetime(2026, 7, 10, 9, 0, 0)
    values = _provider_result_update_values(
        result=ProviderResult("failed", "provider_msg_3", "rejected", permanent=True),
        attempt_count=1,
        now=now,
    )

    assert values["state"] == "failed"
    assert values["next_attempt_at"] is None
    assert values["lease_owner"] is None
    assert values["lease_until"] is None


class _ClaimSession:
    def __init__(self, outboxes: list[object]) -> None:
        self.outboxes = outboxes
        self.committed = False

    async def __aenter__(self) -> "_ClaimSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, _stmt: object) -> _ScalarResult:
        return _ScalarResult(rows=self.outboxes)

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_notification_crash_retry_claims_expired_lease_and_keeps_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers import notification_outbox_worker as worker

    outbox = type("_Outbox", (), {})()
    outbox.id = uuid.uuid4()
    outbox.provider = "sandbox"
    outbox.idempotency_key = "safety:decision-1:contact-1"
    outbox.payload_json = {"summary": "疑似诈骗"}
    outbox.attempt_count = 1
    outbox.created_at = datetime(2026, 7, 10, 8, 0, 0)
    outbox.state = "sending"
    outbox.lease_owner = "crashed-worker"
    outbox.lease_until = datetime(2026, 7, 10, 8, 5, 0)
    outbox.attempt_identity = "old-attempt"
    outbox.updated_at = outbox.created_at

    session = _ClaimSession([outbox])
    sent: list[ClaimedOutbox] = []

    class _Provider:
        async def send(self, claimed: ClaimedOutbox) -> ProviderResult:
            assert session.committed is True
            sent.append(claimed)
            return ProviderResult("accepted", "provider_msg_4")

    async def fake_finish(_claimed: ClaimedOutbox, _result: ProviderResult, *, now: datetime) -> bool:
        return True

    monkeypatch.setattr("app.db.session.async_session", lambda: session)
    monkeypatch.setattr(worker, "resolve_provider", lambda _provider: _Provider())
    monkeypatch.setattr(worker, "_finish_claimed_outbox", fake_finish)

    result = await worker.deliver_due_outbox(limit=1)

    assert result["processed"] == 1
    assert outbox.state == "sending"
    assert outbox.attempt_count == 2
    assert outbox.lease_owner.startswith("notification-outbox:")
    assert outbox.attempt_identity != "old-attempt"
    assert sent[0].idempotency_key == "safety:decision-1:contact-1"


class _FinishSession:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount
        self.added: list[object] = []
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> "_FinishSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, _stmt: object) -> object:
        return type("_WriteResult", (), {"rowcount": self.rowcount})()

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.mark.asyncio
async def test_notification_provider_result_is_conditionally_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers.notification_outbox_worker import _finish_claimed_outbox

    session = _FinishSession(rowcount=0)
    claimed = ClaimedOutbox(
        id=uuid.uuid4(),
        provider="sandbox",
        idempotency_key="stable-key",
        payload_json={"summary": "late result"},
        attempt_count=1,
        attempt_identity="stale-attempt",
        lease_owner="old-worker",
    )

    monkeypatch.setattr("app.db.session.async_session", lambda: session)

    applied = await _finish_claimed_outbox(
        claimed,
        ProviderResult("accepted", "provider_msg_5"),
        now=datetime(2026, 7, 10, 9, 5, 0),
    )

    assert applied is False
    assert session.rolled_back is True
    assert session.committed is False
    assert session.added == []
