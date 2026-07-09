"""POST /api/reminders/{id}/ack confirmation tests."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import create_token
from app.api import reminder_api
from app.db.models import Reminder, ReminderHistory


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _AckSession:
    def __init__(self, reminder: Reminder, history: ReminderHistory | None):
        self.reminder = reminder
        self.history = history
        self.added: list = []
        self._calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def execute(self, stmt):
        self._calls += 1
        # First query: Reminder ownership; second: unacked history
        if self._calls == 1:
            return _ScalarResult(self.reminder)
        return _ScalarResult(self.history)

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj):
        return None


def test_ack_reminder_marks_existing_history(monkeypatch):
    user_id = "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf"
    rid = uuid.uuid4()
    reminder = Reminder(
        id=rid,
        user_id=uuid.UUID(user_id),
        title="吃降压药",
        schedule_type="daily",
        next_fire_at=datetime(2026, 7, 9, 20, 0, 0),
        is_active=True,
        created_by="chat",
    )
    history = ReminderHistory(
        id=uuid.uuid4(),
        reminder_id=rid,
        fired_at=datetime(2026, 7, 9, 20, 0, 0),
        delivered=True,
        acknowledged=False,
    )
    session = _AckSession(reminder, history)
    monkeypatch.setattr("app.db.session.async_session", lambda: session)

    app = FastAPI()
    app.include_router(reminder_api.router, prefix="/api")
    client = TestClient(app)

    token = create_token(user_id, "demo-user", role="elder")
    res = client.post(f"/api/reminders/{rid}/ack", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    payload = res.json()
    assert payload["status"] == "acknowledged"
    assert payload["acknowledged"] is True
    assert history.acknowledged is True


def test_ack_reminder_creates_history_when_missing(monkeypatch):
    user_id = "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf"
    rid = uuid.uuid4()
    reminder = Reminder(
        id=rid,
        user_id=uuid.UUID(user_id),
        title="吃降压药",
        schedule_type="daily",
        next_fire_at=datetime(2026, 7, 9, 20, 0, 0),
        is_active=True,
        created_by="chat",
    )
    session = _AckSession(reminder, None)
    monkeypatch.setattr("app.db.session.async_session", lambda: session)

    app = FastAPI()
    app.include_router(reminder_api.router, prefix="/api")
    client = TestClient(app)

    token = create_token(user_id, "demo-user")
    res = client.post(f"/api/reminders/{rid}/ack", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["status"] == "acknowledged"
    assert len(session.added) == 1
    assert session.added[0].acknowledged is True


def test_ack_reminder_404(monkeypatch):
    user_id = "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf"
    session = _AckSession(
        Reminder(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            title="x",
            schedule_type="once",
            next_fire_at=datetime.utcnow(),
            is_active=True,
            created_by="chat",
        ),
        None,
    )
    # Force missing reminder
    session.reminder = None  # type: ignore[assignment]
    monkeypatch.setattr("app.db.session.async_session", lambda: session)

    app = FastAPI()
    app.include_router(reminder_api.router, prefix="/api")
    client = TestClient(app)
    token = create_token(user_id, "demo-user")
    res = client.post(
        f"/api/reminders/{uuid.uuid4()}/ack",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404
