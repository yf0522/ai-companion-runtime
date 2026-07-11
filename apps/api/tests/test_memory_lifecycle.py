from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import memory as memory_api
from app.api.auth import get_current_user_uuid
from app.memory.lifecycle import (
    MEMORY_POLICY_VERSION,
    build_privacy_safe_family_summary,
    consent_status_for_environment,
    decide_memory_consent,
    detect_sensitivity,
    is_retrievable_memory,
)


class _MappingResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


def test_memory_retrieval_requires_consent_active_and_unexpired():
    active = SimpleNamespace(
        consent_status="granted",
        deletion_state="active",
        retention_until=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
    )
    assert is_retrievable_memory(active)

    assert not is_retrievable_memory(
        SimpleNamespace(consent_status="pending", deletion_state="active", retention_until=None)
    )
    assert not is_retrievable_memory(
        SimpleNamespace(consent_status="granted", deletion_state="deleted", retention_until=None)
    )
    assert not is_retrievable_memory(
        SimpleNamespace(
            consent_status="granted",
            deletion_state="active",
            retention_until=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
        )
    )


def test_sensitivity_detection_marks_eldercare_private_data():
    assert detect_sensitivity("我每天吃降压药") == "health"
    assert detect_sensitivity("银行卡验证码不要告诉骗子") == "financial_safety"
    assert detect_sensitivity("今天天气不错") == "general"


def test_production_memory_storage_defaults_to_pending_consent():
    assert consent_status_for_environment("production") == "pending"
    assert consent_status_for_environment("development") == "granted"


@pytest.mark.asyncio
async def test_memory_owner_approval_creates_grant_and_links_memory_atomically():
    memory_id = uuid.uuid4()
    user_id = uuid.uuid4()
    grant_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.side_effect = [
        _MappingResult(
            {
                "id": memory_id,
                "user_id": user_id,
                "purpose": "preference",
                "sensitivity": "general",
                "retention_until": datetime.now(UTC).replace(tzinfo=None)
                + timedelta(days=30),
                "consent_grant_id": None,
                "consent_status": "pending",
            }
        ),
        _ScalarResult(grant_id),
        AsyncMock(),
    ]

    decision = await decide_memory_consent(
        db,
        memory_id=memory_id,
        user_id=user_id,
        approved=True,
    )

    assert decision == {
        "memory_id": str(memory_id),
        "consent_status": "granted",
        "consent_grant_id": str(grant_id),
    }
    assert db.execute.await_count == 3
    grant_params = db.execute.await_args_list[1].args[0].compile().params
    assert grant_params["consent_version"] == MEMORY_POLICY_VERSION
    assert grant_params["status"] == "granted"
    assert grant_params["user_id"] == user_id
    memory_params = db.execute.await_args_list[2].args[0].compile().params
    assert memory_params["consent_status"] == "granted"
    assert memory_params["consent_grant_id"] == grant_id


@pytest.mark.parametrize(
    ("approved", "consent_status", "grant_id"),
    [
        (True, "granted", uuid.uuid4()),
        (False, "rejected", None),
    ],
)
@pytest.mark.asyncio
async def test_repeated_memory_consent_decision_is_idempotent(
    approved, consent_status, grant_id
):
    memory_id = uuid.uuid4()
    user_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = _MappingResult(
        {
            "id": memory_id,
            "user_id": user_id,
            "purpose": "preference",
            "sensitivity": "general",
            "retention_until": None,
            "consent_grant_id": grant_id,
            "consent_status": consent_status,
        }
    )

    decision = await decide_memory_consent(
        db,
        memory_id=memory_id,
        user_id=user_id,
        approved=approved,
    )

    assert decision["consent_status"] == consent_status
    assert decision["consent_grant_id"] == (str(grant_id) if grant_id else None)
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_rejection_marks_rejected_without_creating_grant():
    memory_id = uuid.uuid4()
    user_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.side_effect = [
        _MappingResult(
            {
                "id": memory_id,
                "user_id": user_id,
                "purpose": "preference",
                "sensitivity": "general",
                "retention_until": None,
                "consent_grant_id": None,
                "consent_status": "pending",
            }
        ),
        AsyncMock(),
    ]

    decision = await decide_memory_consent(
        db,
        memory_id=memory_id,
        user_id=user_id,
        approved=False,
    )

    assert decision["consent_status"] == "rejected"
    assert decision["consent_grant_id"] is None
    assert db.execute.await_count == 2
    update_params = db.execute.await_args_list[1].args[0].compile().params
    assert update_params["consent_status"] == "rejected"


def test_memory_consent_endpoint_returns_404_for_cross_user(monkeypatch):
    owner_id = uuid.uuid4()

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, _stmt):
            return _MappingResult(None)

        async def commit(self):
            raise AssertionError("missing memory must not commit")

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())
    app = FastAPI()
    app.include_router(memory_api.router, prefix="/api")
    app.dependency_overrides[get_current_user_uuid] = lambda: owner_id

    response = TestClient(app).post(
        f"/api/memory/memories/{uuid.uuid4()}/consent",
        json={"approved": True},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Memory not found"


def test_family_summary_excludes_private_memory_content():
    summary = build_privacy_safe_family_summary(
        [
            {
                "id": "task-1",
                "task_type": "medication",
                "status": "completed",
                "due_at": None,
                "completed_at": None,
                "private_transcript": "我住在某小区，银行卡密码是123456",
            },
            {
                "id": "task-2",
                "task_type": "conversation",
                "status": "pending",
                "private_transcript": "不要给家人看",
            },
        ]
    )
    assert summary["summary_type"] == "care_outcomes_only"
    assert summary["total_outcomes"] == 1
    assert summary["items"] == [
        {
            "task_id": "task-1",
            "task_type": "medication",
            "status": "completed",
            "due_at": None,
            "completed_at": None,
        }
    ]
    assert "private_transcript" not in str(summary)


def test_family_summary_maps_real_caretask_terminal_states():
    summary = build_privacy_safe_family_summary(
        [
            {"id": "done-1", "task_type": "medication", "status": "done"},
            {"id": "missed-1", "task_type": "medication", "status": "missed"},
            {"id": "pending-1", "task_type": "medication", "status": "pending"},
        ]
    )

    assert summary["by_status"] == {"completed": 1, "missed": 1}
    assert [item["status"] for item in summary["items"]] == ["completed", "missed"]
