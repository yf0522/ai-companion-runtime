"""AgentHarness family-notification reliability tests."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call
import uuid

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
async def test_medium_decision_pipeline_commits_only_safety_decision(monkeypatch):
    import uuid

    from app.db.models import SafetyDecision
    from app.workers.notification_outbox_worker import persist_nonblocking_safety_decision

    class FakeSession:
        def __init__(self):
            self.added = []
            self.commits = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def add(self, value):
            self.added.append(value)

        async def flush(self):
            self.added[-1].id = uuid.uuid4()

        async def commit(self):
            self.commits += 1

    session = FakeSession()
    monkeypatch.setattr("app.db.session.async_session", lambda: session)

    result = await persist_nonblocking_safety_decision(
        user_id=str(uuid.uuid4()),
        risk_level="medium",
        risk_category="emotional_low",
        trace_id="trace-medium",
    )

    assert len(session.added) == 1
    assert isinstance(session.added[0], SafetyDecision)
    assert session.added[0].action == "record_and_companion"
    assert session.commits == 1
    assert result["outbox_ids"] == []
    assert result["case_opened"] is False
    assert result["webhook_status"] == "not_requested"


@pytest.mark.asyncio
async def test_handle_risk_records_failed_family_notification(monkeypatch):
    harness = AgentHarness()
    stream_mgr = MagicMock()
    stream_mgr.send_risk_alert = AsyncMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_final = AsyncMock()
    stream_mgr.send_delta = AsyncMock()

    monkeypatch.setattr(
        harness,
        "_dispatch_risk_notification",
        AsyncMock(
            return_value={
                    "status": "failed",
                    "records": 0,
                    "webhook_status": None,
                    "error_class": "RuntimeError",
                    "error_code": "notification_dispatch_failed",
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
    monkeypatch.setattr(
        "app.observability.message_evidence.persist_turn_messages",
        AsyncMock(
            side_effect=lambda **kwargs: SimpleNamespace(
                assistant_message_id=kwargs["assistant_message_id"]
            )
        ),
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
    assert recorded[0]["output_json"]["error_class"] == "RuntimeError"
    assert recorded[0]["output_json"]["error_code"] == "notification_dispatch_failed"
    assert "error" not in recorded[0]["output_json"]
    assert recorded[1]["step_name"] == "risk_response_final"
    assert recorded[1]["required"] is True
    assert recorded[1]["output_json"]["notification_status"] == "failed"
    reply = stream_mgr.send_first_reply.await_args.args[0]
    status_delta = stream_mgr.send_delta.await_args.args[0]
    assert "暂时无法联系" in status_delta
    assert "已经通知" not in reply + status_delta


@pytest.mark.asyncio
async def test_handle_risk_hanging_notification_emits_first_reply_and_final_promptly(
    monkeypatch,
):
    harness = AgentHarness()
    stream_mgr = MagicMock()
    stream_mgr.send_risk_alert = AsyncMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_final = AsyncMock()
    stream_mgr.send_delta = AsyncMock()

    async def hang(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(harness, "_dispatch_risk_notification", hang)
    monkeypatch.setattr("app.runtime.agent_harness._RISK_NOTIFICATION_TIMEOUT_S", 0.01)
    monkeypatch.setattr("app.runtime.agent_harness._trace_svc.add_event", AsyncMock())

    result = await asyncio.wait_for(
        harness._handle_risk(
            RiskResult(level="critical", category="health_emergency"),
            stream_mgr,
            trace_id="tr_hang",
            start_time=0.0,
            user_id="user-1",
            session_id="session-1",
        ),
        timeout=0.2,
    )

    assert result["notification_status"]["error_code"] == "notification_dispatch_timeout"
    reply = stream_mgr.send_first_reply.await_args.args[0]
    assert "120" in reply
    assert "已经收到" not in reply
    stream_mgr.send_first_reply.assert_awaited_once()
    stream_mgr.send_final.assert_awaited_once()


@pytest.mark.asyncio
async def test_harness_final_waits_for_notification_and_audit_persistence(monkeypatch):
    harness = AgentHarness()
    stream_mgr = MagicMock()
    stream_mgr.send_risk_alert = AsyncMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_final = AsyncMock()
    stream_mgr.send_delta = AsyncMock()
    notification_release = asyncio.Event()
    notification_completed = asyncio.Event()
    audit_release = asyncio.Event()
    audit_started = asyncio.Event()
    audit_completed = asyncio.Event()
    first_reply_sent = asyncio.Event()

    async def durable_notification(*_args, **_kwargs):
        await notification_release.wait()
        notification_completed.set()
        return {"status": "persisted", "outbox_ids": ["outbox-1"]}

    async def persist_turn_messages(**kwargs):
        audit_started.set()
        await audit_release.wait()
        audit_completed.set()
        return SimpleNamespace(assistant_message_id=kwargs["assistant_message_id"])

    async def send_first_reply(*_args, **_kwargs):
        first_reply_sent.set()

    monkeypatch.setattr(harness, "_dispatch_risk_notification", durable_notification)
    monkeypatch.setattr("app.runtime.agent_harness._RISK_NOTIFICATION_TIMEOUT_S", 1.0)
    monkeypatch.setattr("app.runtime.agent_harness._RISK_TRACE_TIMEOUT_S", 1.0)
    monkeypatch.setattr("app.runtime.agent_harness._trace_svc.add_event", AsyncMock())
    monkeypatch.setattr(
        "app.observability.message_evidence.persist_turn_messages", persist_turn_messages
    )
    stream_mgr.send_first_reply.side_effect = send_first_reply

    task = asyncio.create_task(harness._handle_risk(
        RiskResult(level="critical", category="health_emergency"),
        stream_mgr,
        trace_id="tr_durable",
        start_time=time.monotonic(),
        user_id="user-1",
        session_id="session-1",
    ))

    await asyncio.wait_for(first_reply_sent.wait(), timeout=0.2)
    assert not task.done()
    stream_mgr.send_final.assert_not_awaited()
    notification_release.set()
    await asyncio.wait_for(notification_completed.wait(), timeout=0.2)
    await asyncio.wait_for(audit_started.wait(), timeout=0.2)
    stream_mgr.send_final.assert_not_awaited()
    audit_release.set()
    result = await asyncio.wait_for(task, timeout=0.2)

    assert audit_completed.is_set()
    assert result["notification_status"]["status"] == "persisted"
    assert result["risk_trace_persistence"] == "persisted"
    stream_mgr.send_final.assert_awaited_once()


@pytest.mark.asyncio
async def test_harness_trace_timeout_cleans_up_analysis_task_before_final(monkeypatch):
    harness = AgentHarness()
    stream_mgr = MagicMock()
    stream_mgr.send_risk_alert = AsyncMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_final = AsyncMock()
    stream_mgr.send_delta = AsyncMock()
    analysis_cancelled = asyncio.Event()

    async def blocked_analysis():
        try:
            await asyncio.Event().wait()
        finally:
            analysis_cancelled.set()

    async def persist_turn_messages(**kwargs):
        return SimpleNamespace(assistant_message_id=kwargs["assistant_message_id"])

    monkeypatch.setattr(
        harness,
        "_dispatch_risk_notification",
        AsyncMock(return_value={"status": "persisted", "outbox_ids": []}),
    )
    monkeypatch.setattr("app.runtime.agent_harness._RISK_TRACE_TIMEOUT_S", 0.01)
    monkeypatch.setattr("app.runtime.agent_harness._trace_svc.add_event", AsyncMock())
    monkeypatch.setattr(
        "app.observability.message_evidence.persist_turn_messages",
        persist_turn_messages,
    )

    analysis_task = asyncio.create_task(blocked_analysis())
    result = await harness._handle_risk(
        RiskResult(level="critical", category="health_emergency"),
        stream_mgr,
        trace_id="tr_timeout_cleanup",
        start_time=time.monotonic(),
        user_id="user-1",
        session_id="session-1",
        analysis_trace=analysis_task,
    )

    assert result["risk_trace_persistence"] == "failed"
    assert analysis_cancelled.is_set()
    assert analysis_task.done()
    stream_mgr.send_final.assert_awaited_once()


@pytest.mark.asyncio
async def test_notification_dispatch_failure_log_is_bounded_and_redacted(monkeypatch, caplog):
    async def fail(**_kwargs):
        raise RuntimeError("db secret SQL user text")

    monkeypatch.setattr(
        "app.workers.notification_outbox_worker.create_safety_notification_pipeline",
        fail,
    )
    trace_id = "trace-safe-" + ("x" * 200)
    result = await AgentHarness()._dispatch_risk_notification(
        "user-1", "high", "scam_alert", "bounded summary", trace_id,
    )

    assert result["error_class"] == "RuntimeError"
    assert result["error_code"] == "notification_dispatch_failed"
    assert "db secret" not in caplog.text
    assert f"trace={trace_id[:80]}" in caplog.text
    assert trace_id not in caplog.text


@pytest.mark.asyncio
async def test_handle_risk_emits_final_after_bounded_audit_and_reuses_message_id(monkeypatch):
    harness = AgentHarness()
    stream_mgr = MagicMock()
    stream_mgr.send_risk_alert = AsyncMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_final = AsyncMock()
    stream_mgr.send_delta = AsyncMock()
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

    persisted: list[dict] = []

    async def persist_turn_messages(**kwargs):
        persisted.append(kwargs)
        return SimpleNamespace(assistant_message_id=kwargs["assistant_message_id"])

    monkeypatch.setattr("app.runtime.agent_harness._trace_svc.add_event", fake_add_event)
    monkeypatch.setattr(
        "app.observability.message_evidence.persist_turn_messages",
        persist_turn_messages,
    )
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

    assert order.index("final") > order.index("family_notification")
    assert set(order) == {"analysis", "final", "family_notification", "risk_response_final"}
    assert order.index("risk_response_final") > order.index("analysis")
    assert order.index("final") > order.index("risk_response_final")
    assert stream_mgr.send_risk_alert.await_args == call("high", "")
    final_id = stream_mgr.send_final.await_args.kwargs["message_id"]
    assert persisted[0]["assistant_message_id"] == final_id
    uuid.UUID(final_id)


@pytest.mark.asyncio
async def test_deterministic_caretask_uses_tool_copy_once(monkeypatch):
    harness = AgentHarness()
    stream_mgr = MagicMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_final = AsyncMock()
    stream_mgr.send_delta = AsyncMock()
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
    final_id = stream_mgr.send_final.await_args.kwargs["message_id"]
    persist_call = harness._persist_conversation.await_args
    assert persist_call.kwargs["assistant_message_id"] == final_id
    uuid.UUID(final_id)


@pytest.mark.asyncio
async def test_deterministic_contact_uses_truthful_tool_copy(monkeypatch):
    harness = AgentHarness()
    stream_mgr = MagicMock()
    stream_mgr.send_first_reply = AsyncMock()
    stream_mgr.send_final = AsyncMock()
    stream_mgr.send_delta = AsyncMock()
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
    final_id = stream_mgr.send_final.await_args.kwargs["message_id"]
    persist_call = harness._persist_conversation.await_args
    assert persist_call.kwargs["assistant_message_id"] == final_id
    uuid.UUID(final_id)
