from __future__ import annotations

import importlib
import uuid

import pytest
import sqlalchemy

from app.db.models import NotificationLog


class _FakeQuery:
    def where(self, *args: object, **kwargs: object) -> "_FakeQuery":
        return self

    def order_by(self, *args: object, **kwargs: object) -> "_FakeQuery":
        return self


def _fake_select(*args: object, **kwargs: object) -> _FakeQuery:
    return _FakeQuery()


class _FakeSessionResult:
    def __init__(
        self,
        scalar_value: str | None = None,
        rows: list[object] | None = None,
    ) -> None:
        self._scalar_value = scalar_value
        self._rows = rows or []

    def scalar_one_or_none(self) -> str | None:
        return self._scalar_value

    def scalars(self) -> "_FakeSessionResult":
        return self

    def all(self) -> list[object]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[object], scalar_value: str | None = None) -> None:
        self.rows = rows
        self.scalar_value = scalar_value
        self.calls = 0
        self.added: list[NotificationLog] = []
        self.committed = False

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def execute(self, stmt: object) -> _FakeSessionResult:
        self.calls += 1
        if self.calls == 1:
            return _FakeSessionResult(scalar_value=self.scalar_value)
        return _FakeSessionResult(rows=self.rows)

    def add(self, obj: NotificationLog) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True


class _FakeContact:
    def __init__(self, webhook_url: str | None = None) -> None:
        self.id = uuid.uuid4()
        self.priority = 1
        self.notify_on_levels = ["high", "critical"]
        self.webhook_url = webhook_url
        self.name = "家属A"


@pytest.mark.asyncio
async def test_process_risk_notification_writes_scam_alert_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.workers.notification_worker as worker
    session_module = importlib.import_module("app.db.session")

    fake_session = _FakeSession(
        rows=[_FakeContact()],
        scalar_value="张三",
    )

    monkeypatch.setattr(session_module, "async_session", lambda: fake_session, raising=True)
    monkeypatch.setattr(sqlalchemy, "select", _fake_select, raising=False)
    monkeypatch.setattr(worker, "_send_webhook", lambda *_args: "sent", raising=False)

    result = await worker.process_risk_notification(
        user_id="4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
        risk_level="high",
        risk_category="scam_alert",
        summary="疑似反诈：检测到验证码索要行为，建议先电话确认，不要转账、不报验证码。",
        trace_id="trace_2026_07_09_demo",
    )

    assert result["status"] == "persisted"
    assert result["records"] == 1
    assert fake_session.committed is True
    assert len(fake_session.added) == 1
    record = fake_session.added[0]
    assert record.user_id == uuid.UUID("4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf")
    assert record.risk_category == "scam_alert"
    assert record.risk_level == "high"
    assert record.trace_id == "trace_2026_07_09_demo"
    assert "验证码" in (record.summary or "")
