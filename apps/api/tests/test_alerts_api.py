from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import create_token
from app.api import alerts
from app.api import reminder_api


def test_alerts_requires_authentication():
    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)

    assert client.get("/api/notifications").status_code == 401


def test_list_notifications_returns_empty_when_unavailable():
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


def test_reminders_router_requires_authentication():
    app = FastAPI()
    app.include_router(reminder_api.router, prefix="/api")
    client = TestClient(app)

    assert client.get("/api/reminders").status_code == 401
