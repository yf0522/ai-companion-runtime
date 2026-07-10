from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import alerts, auth, contacts, households
from app.api.auth import create_token
from app.db.models import ContactPoint, Household
from app.workers import notification_outbox_worker as worker


def _auth(user_id: str, role: str = "elder") -> dict[str, str]:
    token = create_token(user_id, f"{role}-user", role=role)
    return {"Authorization": f"Bearer {token}"}


def test_household_has_no_mutable_readiness_boolean() -> None:
    assert "platform_ready" not in Household.__table__.columns
    assert "pilot_ready" not in Household.__table__.columns


def test_contact_verification_is_linked_to_provider_evidence() -> None:
    assert "verification_outbox_id" in ContactPoint.__table__.columns


def test_production_family_registration_requires_valid_invite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.settings, "app_env", "production")

    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    client = TestClient(app)

    res = client.post(
        "/api/auth/register",
        json={"username": "family-no-invite", "password": "secret", "role": "family"},
    )

    assert res.status_code == 403
    assert "invite" in res.json()["detail"]


def test_production_controlled_elder_registration_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.settings, "app_env", "production")
    monkeypatch.setattr(auth.settings, "controlled_elder_enrollment", True)

    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    client = TestClient(app)

    res = client.post(
        "/api/auth/register",
        json={"username": "elder-public", "password": "secret", "role": "elder"},
    )

    assert res.status_code == 403
    assert "managed" in res.json()["detail"]


@pytest.mark.asyncio
async def test_household_invite_accept_rejects_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    actor_id = uuid.uuid4()
    invite = SimpleNamespace(
        id=uuid.uuid4(),
        household_id=uuid.uuid4(),
        elder_user_id=uuid.uuid4(),
        token_hash=households._hash_token("invite-token"),
        permissions=["view_notifications"],
        status="pending",
        expires_at=datetime.utcnow() + timedelta(hours=1),
        replay_nonce=None,
        accepted_by_user_id=None,
        accepted_at=None,
        denied_at=None,
        updated_at=None,
    )

    class _Result:
        def scalar_one_or_none(self):
            return invite

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, _stmt):
            return _Result()

        def add(self, obj):
            if obj.__class__.__name__ == "FamilyBinding":
                obj.id = uuid.uuid4()

        async def flush(self):
            return None

        async def commit(self):
            return None

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())

    first = await households._consume_invite("invite-token", actor_id, "nonce-123456", "accepted")
    assert first["status"] == "accepted"

    invite.status = "pending"
    with pytest.raises(Exception) as exc:
        await households._consume_invite("invite-token", actor_id, "nonce-123456", "accepted")
    assert getattr(exc.value, "status_code", None) == 409


def test_signed_webhook_signature_uses_raw_body_and_rejects_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    outbox_id = uuid.uuid4()
    body = {
        "outbox_id": str(outbox_id),
        "event_type": "delivered",
        "provider_message_id": "provider-msg-1",
    }
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(datetime.utcnow().timestamp()))
    monkeypatch.setattr(worker.settings, "notification_webhook_secret", "secret-for-tests")
    signature = worker._webhook_signature(timestamp, raw)

    called: list[dict] = []

    async def fake_record(**kwargs):
        called.append(kwargs)
        return {"outbox_id": str(outbox_id), "state": "delivered"}

    monkeypatch.setattr(worker, "record_signed_provider_receipt", fake_record)

    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)
    res = client.post(
        "/api/notification-outbox/webhook-receipts",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Companion-Timestamp": timestamp,
            "X-Companion-Signature": signature,
            "X-Companion-Event-Id": "evt-1",
        },
    )

    assert res.status_code == 200
    assert called[0]["raw_body"] == raw

    with pytest.raises(PermissionError):
        worker._verify_webhook_signature(timestamp, "sha256=bad", raw)

    monkeypatch.setattr(worker.settings, "notification_webhook_secret", "")
    with pytest.raises(PermissionError, match="not configured"):
        worker._verify_webhook_signature(timestamp, signature, raw)


def test_operator_case_fsm_rejects_stale_version(monkeypatch: pytest.MonkeyPatch) -> None:
    case_id = uuid.uuid4()
    operator_id = uuid.uuid4()
    row = SimpleNamespace(
        id=case_id,
        status="open",
        state_version=2,
        owner_id=None,
        resolution=None,
        updated_at=None,
        assigned_at=None,
        resolved_at=None,
        reopened_at=None,
    )

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, _stmt):
            class _Result:
                def scalar_one_or_none(self):
                    return row

            return _Result()

        def add(self, _obj):
            return None

        async def commit(self):
            return None

        async def refresh(self, _obj):
            return None

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())

    app = FastAPI()
    app.include_router(alerts.router, prefix="/api")
    client = TestClient(app)
    res = client.patch(
        f"/api/operator/cases/{case_id}",
        json={"status": "assigned", "expected_state_version": 1},
        headers=_auth(str(operator_id), role="operator"),
    )

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "stale_case_version"


@pytest.mark.asyncio
async def test_contact_verification_locks_after_five_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    contact_id = uuid.uuid4()
    household_id = uuid.uuid4()
    row = SimpleNamespace(
        id=contact_id,
        household_id=household_id,
        status="active",
        revoked_at=None,
        verification_locked_at=None,
        verification_attempt_count=4,
        challenge_expires_at=datetime.utcnow() + timedelta(minutes=5),
        verification_challenge_hash=contacts._challenge_hash("123456"),
        verification_state="challenge_pending",
        updated_at=None,
    )

    class _Result:
        def scalar_one_or_none(self):
            return row

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement):
            assert "FOR UPDATE" in str(statement)
            return _Result()

        async def commit(self):
            return None

    async def _managed(_user, permission):
        assert permission == "manage_reminders"
        return SimpleNamespace(elder_id=uuid.uuid4()), household_id

    monkeypatch.setattr(contacts, "_household_for_actor", _managed)
    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())

    with pytest.raises(Exception) as exc:
        await contacts.verify_contact_point(
            contact_id,
            contacts.ChallengeVerify(code="000000"),
            {"sub": str(uuid.uuid4()), "role": "family"},
        )
    assert getattr(exc.value, "status_code", None) == 403
    assert row.verification_attempt_count == 5
    assert row.verification_state == "challenge_locked"
    assert row.verification_locked_at is not None
