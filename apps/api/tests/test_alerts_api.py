from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import create_token
from app.api import alerts
from app.api import reminder_api
from app.db.models import NotificationLog


class _FakeScalars:
    def __init__(self, rows: list[NotificationLog]):
        self._rows = rows

    def all(self) -> list[NotificationLog]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[NotificationLog]):
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSession:
    def __init__(self, rows: list[NotificationLog]):
        self._rows = rows

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def execute(self, stmt: object) -> _FakeResult:
        return _FakeResult(self._rows)

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None


class _AckFakeResult:
    def __init__(self, row: NotificationLog | None):
        self._row = row

    def scalar_one_or_none(self) -> NotificationLog | None:
        return self._row


class _AckFakeSession:
    def __init__(self, row: NotificationLog | None):
        self._row = row

    async def __aenter__(self) -> "_AckFakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def execute(self, stmt: object) -> _AckFakeResult:
        return _AckFakeResult(self._row)

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None


def test_alerts_requires_authentication():
    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)

    assert client.get("/api/notifications").status_code == 401


def test_list_notifications_returns_empty_when_unavailable(monkeypatch):
    class _FailingSession:
        async def __aenter__(self) -> "_FailingSession":
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        async def execute(self, stmt: object) -> object:
            raise RuntimeError("db unavailable")

    monkeypatch.setattr("app.db.session.async_session", lambda: _FailingSession())

    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)

    token = create_token("4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf", "demo-user")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/notifications", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["items"] == []
    assert payload["total"] == 0


def test_list_notifications_returns_scam_alert_from_db(monkeypatch):
    user_id = "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf"
    fake_row = NotificationLog(
        user_id=uuid.UUID(user_id),
        contact_id=None,
        trace_id="trace_2026_01_demo",
        risk_level="high",
        risk_category="scam_alert",
        summary="疑似反诈：检测到验证码索要行为，建议先电话确认，不要转账、不报验证码。",
        webhook_status="sent",
        created_at=datetime(2026, 7, 9, 12, 0, 0),
    )

    monkeypatch.setattr("app.db.session.async_session", lambda: _FakeSession([fake_row]))

    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)

    token = create_token(user_id, "demo-user")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/notifications", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "persisted"
    assert payload["total"] == 1
    assert payload["items"][0]["category"] == "scam_alert"
    assert payload["items"][0]["trace_id"] == "trace_2026_01_demo"
    assert "验证码" in payload["items"][0]["message"]


def test_reminders_router_requires_authentication():
    app = FastAPI()
    app.include_router(reminder_api.router, prefix="/api")
    client = TestClient(app)

    assert client.get("/api/reminders").status_code == 401


def test_ack_notification_marks_acknowledged(monkeypatch):
    user_id = "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf"
    nid = uuid.uuid4()
    fake_row = NotificationLog(
        id=nid,
        user_id=uuid.UUID(user_id),
        contact_id=None,
        trace_id="trace_ack_demo",
        risk_level="high",
        risk_category="scam_alert",
        summary="疑似诈骗，请确认父母未转账",
        webhook_status="sent",
        created_at=datetime(2026, 7, 9, 12, 0, 0),
    )
    monkeypatch.setattr("app.db.session.async_session", lambda: _AckFakeSession(fake_row))

    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)

    # Unit path uses elder role (family path needs FamilyBinding).
    token = create_token(user_id, "demo-user", role="elder")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(f"/api/notifications/{nid}/ack", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "acknowledged"
    assert payload["item"]["status"] == "acknowledged"
    assert fake_row.webhook_status == "acknowledged"


def test_ack_notification_404_when_missing(monkeypatch):
    user_id = "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf"
    monkeypatch.setattr("app.db.session.async_session", lambda: _AckFakeSession(None))

    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)

    token = create_token(user_id, "demo-user")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(
        f"/api/notifications/{uuid.uuid4()}/ack",
        headers=headers,
    )
    assert response.status_code == 404


def test_ack_notification_requires_auth():
    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)
    assert client.post(f"/api/notifications/{uuid.uuid4()}/ack").status_code == 401


def test_family_ack_notification_via_binding(monkeypatch):
    family_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    elder_id = "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf"
    nid = uuid.uuid4()
    fake_row = NotificationLog(
        id=nid,
        user_id=uuid.UUID(elder_id),
        contact_id=None,
        trace_id="trace_family_ack",
        risk_level="high",
        risk_category="scam_alert",
        summary="家属确认任务",
        webhook_status="sent",
        created_at=datetime(2026, 7, 9, 12, 0, 0),
    )

    async def fake_managed_elder(_user: dict):
        return uuid.UUID(elder_id)

    monkeypatch.setattr(alerts, "_get_managed_elder_id", fake_managed_elder)
    monkeypatch.setattr("app.db.session.async_session", lambda: _AckFakeSession(fake_row))

    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)
    token = create_token(family_id, "family-user", role="family")
    res = client.post(
        f"/api/notifications/{nid}/ack",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["item"]["status"] == "acknowledged"
    assert fake_row.webhook_status == "acknowledged"


def test_family_without_binding_cannot_ack(monkeypatch):
    family_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    class _NoBinding:
        def scalar_one_or_none(self):
            return None

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def execute(self, stmt):
            return _NoBinding()

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())

    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)
    token = create_token(family_id, "family-user", role="family")
    res = client.post(
        f"/api/notifications/{uuid.uuid4()}/ack",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
