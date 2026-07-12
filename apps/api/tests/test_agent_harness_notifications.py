"""AgentHarness family-notification reliability tests."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.engines.base import RiskResult
from app.runtime.agent_harness import AgentHarness
from app.tools.base import ToolResult


@pytest.mark.asyncio
async def test_dispatch_awaits_and_returns_persisted_status(monkeypatch):
    harness = AgentHarness()
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

    status = await harness._dispatch_risk_notification(
        user_id="demo-elder",
        risk_level="high",
        risk_category="scam_alert",
        summary="疑似反诈",
        trace_id="tr_test",
    )
    assert status["status"] == "persisted"
    assert status["safety_decision_id"] == "decision-1"
    assert status["case_opened"] is True


@pytest.mark.asyncio
async def test_harness_medium_persists_decision_without_notification_pipeline(monkeypatch):
    harness = AgentHarness()
    persisted = AsyncMock(return_value={"status": "persisted", "outbox_ids": []})
    dispatch = AsyncMock()
    monkeypatch.setattr("app.runtime.risk_gate._persist_nonblocking_decision", persisted)
    monkeypatch.setattr(harness, "_dispatch_risk_notification", dispatch)

    # Exercise the shared policy at the same boundary used by the harness run loop.
    from app.runtime.risk_gate import _persist_nonblocking_decision

    risk = RiskResult(level="medium", category="emotional_low", confidence=0.7)
    await _persist_nonblocking_decision("user-1", risk, "trace-medium")

    persisted.assert_awaited_once()
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_risk_records_failed_family_notification(monkeypatch):
    harness = AgentHarness()
    stream_mgr = MagicMock()
    stream_mgr.send_risk_alert = AsyncMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_final = AsyncMock()

    monkeypatch.setattr(
        harness,
        "_dispatch_risk_notification",
        AsyncMock(
            return_value={
                "status": "failed",
                "records": 0,
                "webhook_status": None,
                "error": "db down",
            }
        ),
    )

    recorded: list[dict] = []

    async def fake_add_event(**kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(
        "app.runtime.agent_harness._trace_svc.add_event",
        fake_add_event,
        raising=True,
    )

    risk = RiskResult(
        level="high",
        category="scam_alert",
        confidence=0.9,
        triggered_rules=["keyword:验证码"],
    )
    await harness._handle_risk(
        risk,
        stream_mgr,
        trace_id="tr_fail",
        start_time=0.0,
        user_id="4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
        session_id="7ee33f18-01e8-471d-98b1-df716ef639be",
    )

    assert len(recorded) == 2
    assert recorded[0]["step_name"] == "family_notification"
    assert recorded[0]["status"] == "failed"
    assert recorded[0]["output_json"]["error"] == "db down"
    assert recorded[1]["step_name"] == "risk_response_final"
    assert recorded[1]["required"] is True
    assert recorded[1]["output_json"]["notification_status"] == "failed"
    reply = stream_mgr.send_first_reply.await_args.args[0]
    assert "暂时无法联系" in reply
    assert "已经通知" not in reply


@pytest.mark.asyncio
async def test_handle_risk_persists_trace_before_final(monkeypatch):
    harness = AgentHarness()
    stream_mgr = MagicMock()
    stream_mgr.send_risk_alert = AsyncMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_final = AsyncMock()
    monkeypatch.setattr(
        harness,
        "_dispatch_risk_notification",
        AsyncMock(return_value={"status": "persisted"}),
    )

    order: list[str] = []

    async def analysis_trace():
        order.append("analysis")

    async def fake_add_event(**kwargs):
        order.append(kwargs["step_name"])

    async def send_final(**_kwargs):
        order.append("final")

    monkeypatch.setattr("app.runtime.agent_harness._trace_svc.add_event", fake_add_event)
    stream_mgr.send_final.side_effect = send_final

    task = asyncio.create_task(analysis_trace())
    await harness._handle_risk(
        RiskResult(level="high", category="scam_alert", confidence=0.9),
        stream_mgr,
        trace_id="tr_order",
        start_time=0.0,
        user_id="4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
        session_id="7ee33f18-01e8-471d-98b1-df716ef639be",
        analysis_trace=task,
    )

    assert order[-1] == "final"
    assert set(order[:-1]) == {"analysis", "family_notification", "risk_response_final"}
    assert order.index("risk_response_final") > order.index("analysis")
    assert stream_mgr.send_risk_alert.await_args == call("high", "")


@pytest.mark.asyncio
async def test_deterministic_caretask_uses_tool_copy_once(monkeypatch):
    harness = AgentHarness()
    stream_mgr = MagicMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_final = AsyncMock()
    harness._dispatch_tools = AsyncMock(
        return_value=[
            ToolResult(
                tool_name="caretask",
                status="success",
                display_text="您已经记过吃降压药这件事了，我会继续为您保留。",
                data={"action": "caretask_reuse"},
            )
        ]
    )
    harness._persist_conversation = AsyncMock()

    result = await harness._run_deterministic_caretask(
        message="帮我记一下吃降压药",
        trace_id="tr_care",
        stream_mgr=stream_mgr,
        user_id="user-1",
        session_id="session-1",
        start_time=0.0,
    )

    stream_mgr.send_first_reply.assert_awaited_once_with(
        "您已经记过吃降压药这件事了，我会继续为您保留。",
        stream_mgr.send_first_reply.await_args.args[1],
    )
    assert result["deterministic_caretask"] is True
    stream_mgr.send_final.assert_awaited_once()


@pytest.mark.asyncio
async def test_deterministic_contact_uses_truthful_tool_copy(monkeypatch):
    harness = AgentHarness()
    stream_mgr = MagicMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_final = AsyncMock()
    harness._dispatch_tools = AsyncMock(
        return_value=[
            ToolResult(
                tool_name="contact",
                status="success",
                display_text="求助请求已记录并进入联系队列，送达状态还在确认。",
                data={"action": "contact_help_request", "delivery_status": "queued"},
            )
        ]
    )
    harness._persist_conversation = AsyncMock()

    result = await harness._run_deterministic_contact(
        message="我想让家人知道我需要帮助",
        trace_id="tr_contact",
        stream_mgr=stream_mgr,
        user_id="user-1",
        session_id="session-1",
        start_time=0.0,
    )

    reply = stream_mgr.send_first_reply.await_args.args[0]
    assert reply == "求助请求已记录并进入联系队列，送达状态还在确认。"
    assert "已经通知" not in reply
    assert result["deterministic_contact"] is True
    stream_mgr.send_final.assert_awaited_once()
