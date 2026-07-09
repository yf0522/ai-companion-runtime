"""AgentHarness family-notification reliability tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engines.base import RiskResult
from app.runtime.agent_harness import AgentHarness


@pytest.mark.asyncio
async def test_dispatch_awaits_and_returns_persisted_status(monkeypatch):
    harness = AgentHarness()
    from app.config.settings import settings as real_settings

    monkeypatch.setattr(real_settings, "enable_celery_tasks", False)

    async def fake_process(*_args, **_kwargs):
        return {
            "status": "persisted",
            "records": 1,
            "webhook_status": "no_contact",
            "error": None,
        }

    import app.workers.notification_worker as worker

    monkeypatch.setattr(worker, "process_risk_notification", fake_process)

    status = await harness._dispatch_risk_notification(
        user_id="demo-elder",
        risk_level="high",
        risk_category="scam_alert",
        summary="疑似反诈",
        trace_id="tr_test",
    )
    assert status["status"] == "persisted"
    assert status["records"] == 1


@pytest.mark.asyncio
async def test_handle_risk_records_failed_family_notification(monkeypatch):
    harness = AgentHarness()
    stream_mgr = MagicMock()
    stream_mgr.send_risk_alert = AsyncMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_final = AsyncMock()

    monkeypatch.setattr(
        harness,
        "_dispatch_risk_notification",
        AsyncMock(
            return_value={
                "status": "failed",
                "records": 0,
                "webhook_status": None,
                "error": "db down",
            }
        ),
    )

    recorded: list[dict] = []

    async def fake_add_event(**kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(
        "app.runtime.agent_harness._trace_svc.add_event",
        fake_add_event,
        raising=True,
    )

    risk = RiskResult(
        level="high",
        category="scam_alert",
        confidence=0.9,
        triggered_rules=["keyword:验证码"],
    )
    await harness._handle_risk(
        risk,
        stream_mgr,
        trace_id="tr_fail",
        start_time=0.0,
        user_id="4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
    )

    assert len(recorded) == 1
    assert recorded[0]["step_name"] == "family_notification"
    assert recorded[0]["status"] == "failed"
    assert recorded[0]["output_json"]["error"] == "db down"


@pytest.mark.asyncio
async def test_process_risk_notification_no_contact_persists(monkeypatch):
    import importlib
    import sqlalchemy
    import uuid

    from app.db.models import NotificationLog
    import app.workers.notification_worker as worker

    session_module = importlib.import_module("app.db.session")

    class _FakeQuery:
        def where(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

    class _FakeResult:
        def scalar_one_or_none(self):
            return "张三"

        def scalars(self):
            return self

        def all(self):
            return []

    class _FakeSession:
        def __init__(self):
            self.added: list[NotificationLog] = []
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, stmt):
            return _FakeResult()

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            self.committed = True

    fake = _FakeSession()
    monkeypatch.setattr(session_module, "async_session", lambda: fake, raising=True)
    monkeypatch.setattr(sqlalchemy, "select", lambda *a, **k: _FakeQuery(), raising=False)

    result = await worker.process_risk_notification(
        user_id="4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
        risk_level="critical",
        risk_category="scam_alert",
        summary="疑似反诈",
        trace_id="tr_no_contact",
    )

    assert result["status"] == "persisted"
    assert result["webhook_status"] == "no_contact"
    assert fake.committed is True
    assert len(fake.added) == 1
    assert fake.added[0].webhook_status == "no_contact"
    assert fake.added[0].user_id == uuid.UUID("4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf")
