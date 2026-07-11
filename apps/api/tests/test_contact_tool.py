from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.tools.contact_tool import ContactFamilyTool


def test_family_contact_request_has_a_non_risk_alert_title():
    from app.api.alerts import _notification_title

    assert _notification_title("medium", "family_contact_request") == "长者请求联系"


class _ContactRows:
    def __init__(self, contacts):
        self._contacts = contacts

    def scalars(self):
        return self

    def all(self):
        return self._contacts


class _ContactSession:
    def __init__(self, contacts):
        self.contacts = contacts
        self.added: list[object] = []
        self.commits = 0
        self.claim_record = SimpleNamespace(
            resource_id=None,
            status="in_progress",
            response_json={},
            error_json={},
            status_code=202,
            updated_at=None,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _statement):
        return _ContactRows(self.contacts)

    async def get(self, model, _record_id):
        if model.__name__ == "IdempotencyRecord":
            return self.claim_record
        return None

    def add(self, value):
        if hasattr(value, "id") and getattr(value, "id", None) is None:
            value.id = uuid.uuid4()
        self.added.append(value)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_contact_pipeline_persists_no_contact_case_atomically(monkeypatch):
    from app.db.models import NotificationLog, OperatorCase, SafetyDecision
    from app.workers import notification_outbox_worker as worker

    session = _ContactSession([])
    finish_called = False

    async def fake_claim(**_kwargs):
        return "won", uuid.uuid4(), None

    async def fake_finish(**kwargs):
        nonlocal finish_called
        finish_called = True

    monkeypatch.setattr(worker, "_claim_family_contact_request", fake_claim)
    monkeypatch.setattr(worker, "_finish_family_contact_request", fake_finish)
    monkeypatch.setattr("app.db.session.async_session", lambda: session)

    result = await worker.create_family_contact_request_pipeline(
        user_id=str(uuid.uuid4()),
        summary="长者主动请求家人联系：需要帮助",
        trace_id="trace-no-contact",
    )

    assert result["delivery_status"] == "no_verified_contact"
    assert session.commits == 1
    assert sum(isinstance(item, SafetyDecision) for item in session.added) == 1
    assert sum(isinstance(item, NotificationLog) for item in session.added) == 1
    assert sum(isinstance(item, OperatorCase) for item in session.added) == 1
    assert finish_called is False
    assert session.claim_record.status == "completed"
    assert session.claim_record.response_json == result
    assert session.claim_record.resource_id is not None


@pytest.mark.asyncio
async def test_contact_pipeline_queues_each_verified_contact(monkeypatch):
    from app.db.models import NotificationLog, NotificationOutbox, OperatorCase
    from app.workers import notification_outbox_worker as worker

    contact = SimpleNamespace(
        id=uuid.uuid4(),
        name="家属",
        webhook_url=None,
    )
    session = _ContactSession([contact])

    async def fake_claim(**_kwargs):
        return "won", uuid.uuid4(), None

    async def fake_finish(**_kwargs):
        return None

    monkeypatch.setattr(worker, "_claim_family_contact_request", fake_claim)
    monkeypatch.setattr(worker, "_finish_family_contact_request", fake_finish)
    monkeypatch.setattr("app.db.session.async_session", lambda: session)

    result = await worker.create_family_contact_request_pipeline(
        user_id=str(uuid.uuid4()),
        summary="长者主动请求家人联系：请给我打电话",
        trace_id="trace-queued",
    )

    assert result["delivery_status"] == "queued"
    assert len(result["outbox_ids"]) == 1
    assert sum(isinstance(item, NotificationOutbox) for item in session.added) == 1
    assert sum(isinstance(item, NotificationLog) for item in session.added) == 1
    assert sum(isinstance(item, OperatorCase) for item in session.added) == 1


@pytest.mark.asyncio
async def test_contact_pipeline_replays_without_duplicate_side_effects(monkeypatch):
    from app.workers import notification_outbox_worker as worker

    replay = {
        "status": "persisted",
        "request_id": str(uuid.uuid4()),
        "outbox_ids": [str(uuid.uuid4())],
        "case_opened": True,
        "delivery_status": "queued",
        "idempotent_replay": True,
    }

    async def fake_claim(**_kwargs):
        return "replay", uuid.uuid4(), replay

    monkeypatch.setattr(worker, "_claim_family_contact_request", fake_claim)
    monkeypatch.setattr(
        "app.db.session.async_session",
        lambda: pytest.fail("replay must not open a side-effect transaction"),
    )

    result = await worker.create_family_contact_request_pipeline(
        user_id=str(uuid.uuid4()),
        summary="长者主动请求家人联系：请给我打电话",
        trace_id="trace-replay",
    )

    assert result == replay


@pytest.mark.asyncio
async def test_contact_failure_cleanup_never_downgrades_a_completed_claim(monkeypatch):
    from app.workers import notification_outbox_worker as worker

    session = _ContactSession([])
    session.claim_record.status = "completed"
    session.claim_record.response_json = {"delivery_status": "queued"}
    monkeypatch.setattr("app.db.session.async_session", lambda: session)

    await worker._finish_family_contact_request(
        record_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        error={"reason": "ambiguous_commit_failure"},
    )

    assert session.claim_record.status == "completed"
    assert session.claim_record.response_json == {"delivery_status": "queued"}
    assert session.commits == 0


@pytest.mark.asyncio
async def test_contact_family_records_request_without_claiming_delivery(monkeypatch):
    captured: dict = {}

    async def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return {
            "status": "persisted",
            "request_id": "request-1",
            "outbox_ids": [],
            "case_opened": True,
            "delivery_status": "no_verified_contact",
        }

    monkeypatch.setattr(
        "app.tools.contact_tool.create_family_contact_request_pipeline",
        fake_pipeline,
    )

    result = await ContactFamilyTool().execute(
        {
            "action": "request_contact",
            "query": "我想让家人知道我需要帮助",
            "user_id": str(uuid.uuid4()),
            "session_id": str(uuid.uuid4()),
            "trace_id": "trace-help",
        }
    )

    assert result.status == "success"
    assert result.data["action"] == "contact_help_request"
    assert result.data["delivery_status"] == "no_verified_contact"
    assert "没有可用的已验证联系人" in result.display_text
    assert "已经通知" not in result.display_text
    assert captured["trace_id"] == "trace-help"
    assert captured["summary"] == "长者主动请求家人联系：我想让家人知道我需要帮助"


@pytest.mark.asyncio
async def test_contact_family_reports_queued_not_delivered(monkeypatch):
    async def fake_pipeline(**_kwargs):
        return {
            "status": "persisted",
            "request_id": "request-2",
            "outbox_ids": ["outbox-1"],
            "case_opened": True,
            "delivery_status": "queued",
        }

    monkeypatch.setattr(
        "app.tools.contact_tool.create_family_contact_request_pipeline",
        fake_pipeline,
    )

    result = await ContactFamilyTool().execute(
        {
            "query": "请家人给我打电话",
            "user_id": str(uuid.uuid4()),
            "trace_id": "trace-help-queued",
        }
    )

    assert result.status == "success"
    assert result.data["delivery_status"] == "queued"
    assert "进入联系队列" in result.display_text
    assert "已经送达" not in result.display_text


@pytest.mark.asyncio
async def test_contact_family_stays_persisted_when_broker_scheduling_fails(monkeypatch):
    async def fake_pipeline(**_kwargs):
        return {
            "status": "persisted",
            "request_id": "request-3",
            "outbox_ids": ["outbox-1"],
            "case_opened": True,
            "delivery_status": "queued",
        }

    def fail_schedule():
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        "app.tools.contact_tool.create_family_contact_request_pipeline",
        fake_pipeline,
    )
    monkeypatch.setattr("app.tools.contact_tool.settings.enable_celery_tasks", True)
    monkeypatch.setattr("app.tools.contact_tool.deliver_notification_outbox.delay", fail_schedule)

    result = await ContactFamilyTool().execute(
        {
            "query": "请家人给我打电话",
            "user_id": str(uuid.uuid4()),
            "trace_id": "trace-help-broker-down",
        }
    )

    assert result.status == "success"
    assert result.data["delivery_status"] == "queued"
    assert result.data["delivery_task_queued"] is False
    assert result.data["delivery_schedule_error"] == "broker_unavailable"
    assert "送达状态还在确认" in result.display_text
