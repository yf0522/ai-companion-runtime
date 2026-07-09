from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import create_token
from app.api import alerts


def test_alerts_requires_authentication():
    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)

    assert client.get("/api/reminders").status_code == 401
    assert client.get("/api/notifications").status_code == 401


def test_list_reminders_returns_demo_item():
    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)

    token = create_token("d2f8e8b8-8f6b-4c55-95b4-0d0f3e5ce9d1", "demo-user")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/reminders", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "demo_placeholder"
    items = payload["items"]
    assert len(items) == 1
    item = items[0]
    assert item["timer_type"] == "reminder"
    assert item["status"] == "active"


def test_list_notifications_returns_demo_item():
    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)

    token = create_token("4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf", "demo-user")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/notifications", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "demo_placeholder"
    items = payload["items"]
    assert len(items) == 1
    item = items[0]
    assert item["category"] == "scam_alert"
    assert item["status"] == "roadmap"
