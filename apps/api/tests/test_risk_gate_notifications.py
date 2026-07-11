"""Risk-gate family-notification reliability (migrated from deleted AgentHarness)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engines.base import RiskResult
from app.runtime import risk_gate


@pytest.mark.asyncio
async def test_dispatch_awaits_and_returns_persisted_status(monkeypatch):
    from app.config.settings import settings as real_settings

    monkeypatch.setattr(real_settings, "enable_celery_tasks", False)

    async def fake_pipeline(**_kwargs):
        return {
            "status": "persisted",
            "safety_decision_id": "decision-1",
            "outbox_ids": [],
            "case_opened": True,
        }

    import app.workers.notification_outbox_worker as worker

    monkeypatch.setattr(worker, "create_safety_notification_pipeline", fake_pipeline)

    status = await risk_gate._dispatch_family_notify(
        user_id="demo-elder",
        risk=RiskResult(level="high", category="scam_alert", confidence=0.9),
        trace_id="tr_test",
    )
    assert status["status"] == "persisted"
    assert status["safety_decision_id"] == "decision-1"
    assert status["case_opened"] is True


@pytest.mark.asyncio
async def test_emit_risk_block_honest_when_notify_fails(monkeypatch):
    stream_mgr = MagicMock()
    stream_mgr.send_risk_alert = AsyncMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_final = AsyncMock()

    monkeypatch.setattr(
        risk_gate,
        "_dispatch_family_notify",
        AsyncMock(
            return_value={
                "status": "failed",
                "records": 0,
                "webhook_status": None,
                "error": "db down",
            }
        ),
    )

    risk = RiskResult(
        level="high",
        category="scam_alert",
        confidence=0.9,
        triggered_rules=["keyword:验证码"],
    )
    await risk_gate._emit_risk_block(
        risk,
        stream_mgr,
        trace_id="tr_fail",
        start=0.0,
        user_id="4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
    )

    reply = stream_mgr.send_first_reply.await_args.args[0]
    assert "暂时无法联系" in reply
    assert "已经通知" not in reply
    stream_mgr.send_final.assert_awaited_once()
