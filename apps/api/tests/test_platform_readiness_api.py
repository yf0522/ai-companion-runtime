from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.auth import create_token
from app.main import app
from app.runtime.readiness import READY, UNSAFE


def _auth(role: str) -> dict[str, str]:
    token = create_token(str(uuid.uuid4()), f"{role}-readiness-test", role=role)
    return {"Authorization": f"Bearer {token}"}


def _public_payload(status: str) -> dict:
    return {
        "contract_version": "platform-readiness.v1",
        "scope": "platform",
        "status": status,
        "checked_at": "2026-07-12T08:30:00Z",
        "duration_ms": 12.4,
        "checks": {
            "redis": {
                "status": status,
                "detail": "redis responded" if status == READY else "redis is unavailable",
                "duration_ms": 1.3,
            }
        },
    }


@pytest.mark.parametrize(("status", "http_status"), [(READY, 200), (UNSAFE, 503)])
def test_public_readiness_keeps_status_semantics(monkeypatch, status, http_status):
    async def _assess():
        return _public_payload(status)

    monkeypatch.setattr("app.runtime.readiness.assess_platform_readiness", _assess)

    response = TestClient(app).get("/ready")

    assert response.status_code == http_status
    assert response.json()["status"] == status


def test_operator_platform_readiness_requires_authentication():
    response = TestClient(app).get("/api/operator/platform/readiness")

    assert response.status_code == 401


@pytest.mark.parametrize("role", ["elder", "family", "admin", "ops"])
def test_operator_platform_readiness_rejects_every_non_exact_operator_role(role):
    response = TestClient(app).get(
        "/api/operator/platform/readiness",
        headers=_auth(role),
    )

    assert response.status_code == 403


def test_operator_platform_readiness_returns_repair_metadata_and_no_store(monkeypatch):
    async def _assess():
        return _public_payload(UNSAFE)

    monkeypatch.setattr("app.api.platform.assess_platform_readiness", _assess)

    response = TestClient(app).get(
        "/api/operator/platform/readiness",
        headers=_auth("operator"),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["status"] == UNSAFE
    assert payload["checks"][0] == {
        "id": "redis",
        "label": "Redis memory and queue store",
        "status": UNSAFE,
        "summary": "redis is unavailable",
        "duration_ms": 1.3,
        "owner": "Platform runtime",
        "next_action": "Verify the active Redis URL and authentication profile.",
        "runbook": "platform-readiness#redis",
    }


def test_operator_platform_readiness_does_not_expose_dependency_errors(monkeypatch, caplog):
    secret = "redis://:top-secret@redis.example.test:6379/0"

    async def _raises(_settings):
        raise RuntimeError(secret)

    async def _assess():
        from app.config.settings import Settings
        from app.runtime.readiness import assess_platform_readiness

        return await assess_platform_readiness(
            Settings(),
            checks=(("redis", _raises),),
            allow_partial_checks=True,
        )

    monkeypatch.setattr("app.api.platform.assess_platform_readiness", _assess)

    response = TestClient(app).get(
        "/api/operator/platform/readiness",
        headers=_auth("operator"),
    )

    assert response.status_code == 200
    assert response.json()["status"] == UNSAFE
    assert secret not in response.text
    assert secret not in caplog.text
    assert secret not in json.dumps(response.json())
