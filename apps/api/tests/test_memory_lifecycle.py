from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.memory.lifecycle import (
    build_privacy_safe_family_summary,
    consent_status_for_environment,
    detect_sensitivity,
    is_retrievable_memory,
)


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
