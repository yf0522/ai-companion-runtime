"""Tests for the risk engine — elderly companion: health, scam, emotional."""
import uuid

import pytest
from app.engines.base import AnalyzerInput
from app.engines.risk_engine import RiskEngine, _normalize_text


@pytest.fixture
def engine():
    return RiskEngine()


def _input(msg: str) -> AnalyzerInput:
    return AnalyzerInput(user_id="test", session_id="test", message=msg, trace_id="t1")


def test_normalize_removes_spaces_between_cjk():
    assert "胸口疼" in _normalize_text("胸 口 疼")


def test_normalize_lowercases():
    assert "scam" in _normalize_text("SCAM")


@pytest.mark.asyncio
async def test_critical_chest_pain(engine):
    result = await engine.analyze(_input("胸口疼得厉害"))
    assert result.level == "critical"
    assert result.category == "health_emergency"


@pytest.mark.asyncio
async def test_critical_cant_breathe(engine):
    result = await engine.analyze(_input("喘不上气了"))
    assert result.level == "critical"
    assert result.category == "health_emergency"


@pytest.mark.asyncio
async def test_high_scam_transfer(engine):
    result = await engine.analyze(_input("有人让我转钱"))
    assert result.level == "high"
    assert result.category == "scam_alert"


@pytest.mark.asyncio
async def test_exact_scam_transfer_pressure_and_code(engine):
    result = await engine.analyze(
        _input("有人打电话催我马上转账，还让我告诉他验证码，我还没有操作")
    )
    assert result.level == "high"
    assert result.category == "scam_alert"
    assert any(rule.startswith("pattern:") for rule in result.triggered_rules)


@pytest.mark.asyncio
async def test_exact_acute_health_compound_pattern(engine):
    result = await engine.analyze(_input("我胸口很疼，也呼吸困难"))
    assert result.level == "critical"
    assert result.category == "health_emergency"


@pytest.mark.asyncio
async def test_exact_user_acute_health_phrase_with_breathing_modifier(engine):
    result = await engine.analyze(_input("我现在胸口很痛，呼吸也很困难"))
    assert result.level == "critical"
    assert result.category == "health_emergency"
    assert any(rule.startswith("pattern:") for rule in result.triggered_rules)


@pytest.mark.asyncio
async def test_critical_compound_pattern_path(engine):
    result = await engine.analyze(_input("我胸部很痛，也透不过气"))
    assert result.level == "critical"
    assert result.category == "health_emergency"
    assert any(rule.startswith("pattern:") for rule in result.triggered_rules)


@pytest.mark.asyncio
async def test_high_scam_police(engine):
    result = await engine.analyze(_input("公安局打电话说我涉案"))
    assert result.level == "high"
    assert result.category == "scam_alert"


@pytest.mark.asyncio
async def test_high_scam_password(engine):
    result = await engine.analyze(_input("对方要我的银行卡密码"))
    assert result.level == "high"
    assert result.category == "scam_alert"


@pytest.mark.asyncio
async def test_ideation_我想死_is_high_emotional_crisis(engine):
    result = await engine.analyze(_input("我想死"))
    assert result.level == "high"
    assert result.category == "emotional_crisis"
    assert any("想死" in r or "我想死" in r for r in result.triggered_rules)


@pytest.mark.asyncio
async def test_ideation_不想活了_is_high(engine):
    result = await engine.analyze(_input("我不想活了"))
    assert result.level == "high"
    assert result.category == "emotional_crisis"


@pytest.mark.asyncio
async def test_negated_我没有想死_is_low(engine):
    result = await engine.analyze(_input("我没有想死"))
    assert result.level == "low"


@pytest.mark.asyncio
async def test_safe_context_累死_is_low(engine):
    result = await engine.analyze(_input("今天累死了"))
    assert result.level == "low"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected_level"),
    [
        ("今天累死了，现在胸口很疼，也呼吸困难", "critical"),
        ("我没有胸痛但呼吸困难", "critical"),
        ("我胸口不痛，也没有呼吸困难", "low"),
        ("新闻里说：\u201c我现在胸口疼，也呼吸困难\u201d", "low"),
        ("例如\u201c胸口疼呼吸困难\u201d这种情况要及时就医", "low"),
        ("新闻里说：\u201c我现在胸口疼呼吸困难\u201d，但我现在胸口疼呼吸困难", "critical"),
        ("新闻里说\u201c有人胸口疼呼吸困难\u201d我现在胸口疼呼吸困难", "critical"),
        ("新闻看完后我胸口疼得厉害", "critical"),
        ("看了新闻以后我胸口疼得厉害", "critical"),
        ("我看新闻时胸口疼得厉害", "critical"),
        ("新闻里说有人胸口疼得厉害", "low"),
    ],
)
async def test_risk_match_context_is_span_clause_and_modality_aware(
    engine, message, expected_level
):
    result = await engine.analyze(_input(message))
    assert result.level == expected_level


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "新闻里说我妈妈胸口疼得厉害",
        "新闻里说我胸口疼得厉害",
        "新闻报道中提到我朋友胸口疼呼吸困难",
    ],
)
async def test_reported_possessive_subject_does_not_become_first_person_assertion(
    engine, message
):
    result = await engine.analyze(_input(message))

    assert result.level == "low"
    assert result.category == "none"


@pytest.mark.asyncio
async def test_safety_message_emotional_crisis_has_cn_hotlines():
    from app.runtime.risk_gate import load_safety_message

    msg = load_safety_message("high", "emotional_crisis")
    assert "12356" in msg or "400-161-9995" in msg
    assert "988" not in msg
    assert "111" not in msg


def test_safety_message_lookup_does_not_read_config_on_request(monkeypatch):
    import builtins

    from app.runtime.risk_gate import load_safety_message

    def fail_open(*_args, **_kwargs):
        raise AssertionError("risk response performed request-time file I/O")

    monkeypatch.setattr(builtins, "open", fail_open)
    assert load_safety_message("high", "emotional_crisis")


@pytest.mark.asyncio
async def test_risk_gate_blocks_before_pi_sidecar(monkeypatch):
    from unittest.mock import AsyncMock

    from app.engines.base import RiskResult
    from app.runtime.risk_gate import run_risk_gate

    async def fake_analyze(self, input):
        return RiskResult(
            level="high",
            category="emotional_crisis",
            confidence=0.9,
            triggered_rules=["keyword:我想死"],
        )

    monkeypatch.setattr(
        "app.engines.risk_engine.RiskEngine.analyze",
        fake_analyze,
    )
    notify = AsyncMock(
        return_value={
            "status": "persisted",
            "outbox_ids": ["outbox-1"],
            "webhook_status": "queued",
        }
    )
    monkeypatch.setattr(
        "app.runtime.risk_gate._dispatch_family_notify",
        notify,
    )

    stream = AsyncMock()
    stream.send_trace = AsyncMock()
    stream.send_risk_alert = AsyncMock()
    stream.send_first_reply = AsyncMock()
    stream.send_final = AsyncMock()

    gate = await run_risk_gate(
        user_id="u1",
        session_id="s1",
        message="我想死",
        stream_mgr=stream,
        timeout_ms=500,
    )
    assert gate.blocked is True
    assert gate.metadata.get("blocked_by_risk") is True
    stream.send_first_reply.assert_awaited()
    first_msg = stream.send_first_reply.await_args.args[0]
    assert "12356" in first_msg or "400-161-9995" in first_msg
    assert "988" not in first_msg
    # risk_alert must not carry the same safety paragraph (bubble would duplicate).
    stream.send_risk_alert.assert_awaited()
    alert_args = stream.send_risk_alert.await_args.args
    assert alert_args[0] == "high"
    assert alert_args[1] == ""
    notify.assert_awaited()


def test_safety_response_does_not_claim_unconfirmed_delivery():
    from app.runtime.risk_gate import build_safety_response

    queued = build_safety_response(
        "请拨打 110 或 120。",
        {"status": "persisted", "outbox_ids": ["outbox-1"], "webhook_status": "queued"},
    )
    assert "请求已记录" in queued
    assert "正在发送" not in queued
    assert "已经收到" not in queued

    no_contact = build_safety_response(
        "请拨打 110 或 120。",
        {"status": "persisted", "outbox_ids": [], "webhook_status": "no_contact"},
    )
    assert "没有可通知" in no_contact
    assert "已通知" not in no_contact


@pytest.mark.asyncio
async def test_high_health_concern(engine):
    result = await engine.analyze(_input("这两天一直头疼"))
    assert result.level == "high"
    assert result.category == "health_emergency"


@pytest.mark.asyncio
async def test_medium_lonely(engine):
    result = await engine.analyze(_input("一个人好无聊"))
    assert result.level == "medium"
    assert result.category == "emotional_low"


@pytest.mark.asyncio
async def test_exact_loneliness_anhedonia_pattern(engine):
    result = await engine.analyze(_input("我最近总觉得很孤单，什么都不想做"))
    assert result.level == "medium"
    assert result.category == "emotional_low"
    assert any(rule.startswith("medium_pattern:") for rule in result.triggered_rules)


@pytest.mark.asyncio
async def test_medium_risk_gate_persists_without_family_outbox(monkeypatch):
    from unittest.mock import AsyncMock

    from app.runtime.risk_gate import run_risk_gate

    persisted = AsyncMock(return_value={"status": "persisted", "outbox_ids": []})
    family_notify = AsyncMock()
    monkeypatch.setattr("app.runtime.risk_gate.persist_nonblocking_decision", persisted)
    monkeypatch.setattr("app.runtime.risk_gate._dispatch_family_notify", family_notify)
    stream = AsyncMock()

    gate = await run_risk_gate(
        user_id="u1",
        session_id="s1",
        message="我最近总觉得很孤单，什么都不想做",
        stream_mgr=stream,
        timeout_ms=500,
    )

    assert gate.blocked is False
    assert gate.metadata["decision_persistence"] == {"status": "persisted", "outbox_ids": []}
    persisted.assert_awaited_once()
    family_notify.assert_not_awaited()
    stream.send_risk_alert.assert_awaited_once_with("medium", "")


@pytest.mark.asyncio
async def test_medium_risk_persistence_degradation_is_bounded_and_nonblocking(monkeypatch):
    from unittest.mock import AsyncMock

    from app.engines.base import RiskResult
    from app.runtime.risk_gate import run_risk_gate

    monkeypatch.setattr(
        "app.runtime.risk_gate._analyze_risk",
        AsyncMock(return_value=RiskResult(level="medium", category="emotional_low")),
    )
    monkeypatch.setattr(
        "app.runtime.risk_gate.persist_nonblocking_decision",
        AsyncMock(return_value={
            "status": "failed", "outbox_ids": [],
            "error_class": "RuntimeError", "error_code": "decision_persistence_failed",
        }),
    )
    family_notify = AsyncMock()
    monkeypatch.setattr("app.runtime.risk_gate._dispatch_family_notify", family_notify)

    gate = await run_risk_gate(
        user_id="u1", session_id="s1", message="我很孤单", stream_mgr=AsyncMock()
    )

    assert gate.blocked is False
    assert gate.metadata["decision_persistence"]["error_code"] == "decision_persistence_failed"
    assert "error" not in gate.metadata["decision_persistence"]
    family_notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_family_notify_failure_is_truthful_bounded_and_redacted(monkeypatch, caplog):
    from app.engines.base import RiskResult
    from app.runtime.risk_gate import (
        _dispatch_family_notify,
        build_safety_response,
        load_safety_message,
    )

    async def fail(**_kwargs):
        raise RuntimeError("provider secret SQL user message")

    monkeypatch.setattr(
        "app.workers.notification_outbox_worker.create_safety_notification_pipeline",
        fail,
    )
    trace_id = "trace-family-" + ("x" * 200)
    risk = RiskResult(level="critical", category="health_emergency")

    result = await _dispatch_family_notify("user-1", risk, trace_id)
    response = build_safety_response(
        load_safety_message(risk.level, risk.category), result
    )

    assert result == {
        "status": "failed",
        "outbox_ids": [],
        "error_class": "RuntimeError",
        "error_code": "family_notify_failed",
    }
    assert "provider secret" not in caplog.text
    assert f"trace={trace_id[:80]}" in caplog.text
    assert trace_id not in caplog.text
    assert "RuntimeError" in caplog.text
    assert "code=family_notify_failed" in caplog.text
    assert "暂时无法联系" in response
    assert "已经通知" not in response


@pytest.mark.asyncio
async def test_pi_critical_persistence_failure_still_emits_truthful_guidance(monkeypatch):
    from unittest.mock import AsyncMock

    from app.engines.base import RiskResult
    from app.runtime.risk_gate import run_risk_gate

    monkeypatch.setattr(
        "app.runtime.risk_gate._analyze_risk",
        AsyncMock(
            return_value=RiskResult(
                level="critical",
                category="health_emergency",
                confidence=0.95,
            )
        ),
    )
    monkeypatch.setattr(
        "app.runtime.risk_gate._dispatch_family_notify",
        AsyncMock(return_value={"status": "failed", "outbox_ids": [], "error": "db down"}),
    )
    stream = AsyncMock()

    gate = await run_risk_gate(
        user_id="u1",
        session_id="s1",
        message="我现在胸口很痛，呼吸也很困难",
        stream_mgr=stream,
    )

    assert gate.blocked is True
    reply = stream.send_first_reply.await_args.args[0]
    assert "120" in reply
    assert "暂时无法联系" in stream.send_delta.await_args.args[0]
    assert "已经收到" not in reply
    stream.send_final.assert_awaited_once()


@pytest.mark.asyncio
async def test_blocked_turn_persists_messages_and_redacted_trace_events(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.engines.base import RiskResult
    from app.runtime.risk_gate import run_risk_gate

    monkeypatch.setattr(
        "app.runtime.risk_gate._analyze_risk",
        AsyncMock(return_value=RiskResult(
            level="high", category="scam_alert", triggered_rules=["keyword:验证码 654321"]
        )),
    )
    monkeypatch.setattr(
        "app.runtime.risk_gate._dispatch_family_notify",
        AsyncMock(return_value={"outbox_ids": ["opaque-id"], "webhook_status": "queued"}),
    )
    async def persist_messages(**kwargs):
        return SimpleNamespace(assistant_message_id=kwargs["assistant_message_id"])

    persist = AsyncMock(side_effect=persist_messages)
    add_event = AsyncMock()
    monkeypatch.setattr("app.observability.message_evidence.persist_turn_messages", persist)
    monkeypatch.setattr("app.observability.trace_service.TraceService.add_event", add_event)
    stream = AsyncMock()

    gate = await run_risk_gate(
        user_id="user-1", session_id="session-1", message="验证码 654321",
        stream_mgr=stream,
    )

    assert gate.metadata["audit_persisted"] is True
    stored = persist.await_args.kwargs
    assert stored["user_content"] == "验证码 654321"
    assert stored["assistant_content"] == gate.metadata["response_text"]
    assert stored["trace_id"] == gate.trace_id
    final_id = stream.send_final.await_args.kwargs["message_id"]
    assert stored["assistant_message_id"] == final_id
    assert gate.metadata["assistant_message_id"] == final_id
    uuid.UUID(final_id)
    assert [call.kwargs["step_name"] for call in add_event.await_args_list] == [
        "incoming_turn", "final_outcome"
    ]
    assert [call.kwargs["step_index"] for call in add_event.await_args_list] == [0, 99]
    assert all(call.kwargs["required"] is True for call in add_event.await_args_list)
    event_json = str([call.kwargs for call in add_event.await_args_list])
    assert "654321" not in event_json
    assert gate.metadata["response_text"] not in event_json
    assert "triggered_rule_types" in event_json
    stream.send_final.assert_awaited_once()


@pytest.mark.asyncio
async def test_blocked_turn_hanging_audit_cannot_suppress_final(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from app.engines.base import RiskResult
    from app.runtime.risk_gate import run_risk_gate

    async def hang(**_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "app.runtime.risk_gate._analyze_risk",
        AsyncMock(return_value=RiskResult(level="critical", category="health_emergency")),
    )
    monkeypatch.setattr(
        "app.runtime.risk_gate._dispatch_family_notify",
        AsyncMock(return_value={"status": "failed", "outbox_ids": []}),
    )
    monkeypatch.setattr("app.runtime.risk_gate._persist_blocked_turn_evidence", hang)
    monkeypatch.setattr("app.runtime.risk_gate._BLOCKED_AUDIT_TIMEOUT_S", 0.001)
    stream = AsyncMock()

    gate = await run_risk_gate(
        user_id="user-1", session_id="session-1", message="胸口痛，呼吸困难",
        stream_mgr=stream,
    )

    assert gate.blocked is True
    assert gate.metadata["audit_persisted"] is False
    assert gate.metadata["audit_persistence"] == "failed"
    assert gate.metadata["audit_error"] == "TimeoutError"
    assert "120" in gate.metadata["response_text"]
    stream.send_first_reply.assert_awaited_once()
    stream.send_final.assert_awaited_once()


@pytest.mark.asyncio
async def test_risk_gate_hanging_notification_emits_promptly_without_delivery_claim(
    monkeypatch,
):
    import asyncio
    import time
    from unittest.mock import AsyncMock

    from app.engines.base import RiskResult
    from app.runtime.risk_gate import run_risk_gate

    async def hang(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "app.runtime.risk_gate._analyze_risk",
        AsyncMock(return_value=RiskResult(level="critical", category="health_emergency")),
    )
    monkeypatch.setattr("app.runtime.risk_gate._dispatch_family_notify", hang)
    monkeypatch.setattr("app.runtime.risk_gate._NOTIFICATION_TIMEOUT_S", 0.01)
    stream = AsyncMock()

    started = time.monotonic()
    gate = await asyncio.wait_for(
        run_risk_gate(
            user_id="user-1",
            session_id="session-1",
            message="胸口疼呼吸困难",
            stream_mgr=stream,
        ),
        timeout=0.2,
    )

    assert time.monotonic() - started < 0.2
    assert gate.metadata["notification_status"]["error_code"] == "family_notify_timeout"


@pytest.mark.asyncio
async def test_risk_gate_first_reply_is_prompt_and_final_waits_for_durable_writes(monkeypatch):
    import asyncio
    import time
    from unittest.mock import AsyncMock

    from app.engines.base import RiskResult
    from app.runtime.risk_gate import run_risk_gate

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

    async def durable_audit(**_kwargs):
        audit_started.set()
        await audit_release.wait()
        audit_completed.set()

    async def send_first_reply(*_args, **_kwargs):
        first_reply_sent.set()

    monkeypatch.setattr(
        "app.runtime.risk_gate._analyze_risk",
        AsyncMock(return_value=RiskResult(level="critical", category="health_emergency")),
    )
    monkeypatch.setattr(
        "app.runtime.risk_gate._dispatch_family_notify",
        durable_notification,
    )
    monkeypatch.setattr("app.runtime.risk_gate._persist_blocked_turn_evidence", durable_audit)
    monkeypatch.setattr("app.runtime.risk_gate._NOTIFICATION_TIMEOUT_S", 1.0)
    monkeypatch.setattr("app.runtime.risk_gate._BLOCKED_AUDIT_TIMEOUT_S", 1.0)
    stream = AsyncMock()
    stream.send_first_reply.side_effect = send_first_reply

    started = time.monotonic()
    task = asyncio.create_task(run_risk_gate(
        user_id="user-1", session_id="session-1", message="胸口疼呼吸困难", stream_mgr=stream
    ))

    await asyncio.wait_for(first_reply_sent.wait(), timeout=0.2)
    assert time.monotonic() - started < 0.2
    assert not task.done()
    stream.send_final.assert_not_awaited()

    notification_release.set()
    await asyncio.wait_for(notification_completed.wait(), timeout=0.2)
    await asyncio.wait_for(audit_started.wait(), timeout=0.2)
    assert not task.done()
    stream.send_final.assert_not_awaited()

    audit_release.set()
    gate = await asyncio.wait_for(task, timeout=0.2)
    assert audit_completed.is_set()
    assert gate.metadata["audit_persistence"] == "persisted"
    assert gate.metadata["notification_status"]["outbox_count"] == 1
    stream.send_first_reply.assert_awaited_once()
    stream.send_final.assert_awaited_once()


@pytest.mark.asyncio
async def test_blocked_turn_raising_audit_cannot_suppress_emergency(monkeypatch, caplog):
    from unittest.mock import AsyncMock

    from app.engines.base import RiskResult
    from app.runtime.risk_gate import run_risk_gate

    async def fail(**_kwargs):
        raise RuntimeError("postgres secret SQL user text")

    monkeypatch.setattr(
        "app.runtime.risk_gate._analyze_risk",
        AsyncMock(return_value=RiskResult(level="critical", category="health_emergency")),
    )
    monkeypatch.setattr(
        "app.runtime.risk_gate._dispatch_family_notify",
        AsyncMock(return_value={"status": "failed", "outbox_ids": []}),
    )
    monkeypatch.setattr("app.runtime.risk_gate._persist_blocked_turn_evidence", fail)
    stream = AsyncMock()

    gate = await run_risk_gate(
        user_id="user-1", session_id="session-1", message="胸口痛",
        stream_mgr=stream,
    )

    assert gate.metadata["audit_persisted"] is False
    assert gate.metadata["audit_error"] == "RuntimeError"
    assert "postgres secret" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert "trace=trace_" in caplog.text
    assert "code=blocked_audit_failed" in caplog.text
    assert "120" in gate.metadata["response_text"]
    stream.send_first_reply.assert_awaited_once()
    stream.send_final.assert_awaited_once()


@pytest.mark.asyncio
async def test_normal_message_is_low(engine):
    result = await engine.analyze(_input("今天天气真好"))
    assert result.level == "low"


@pytest.mark.asyncio
async def test_safe_context_laugh(engine):
    result = await engine.analyze(_input("笑死我了"))
    assert result.level == "low"


@pytest.mark.asyncio
async def test_negated_keyword_not_triggered(engine):
    result = await engine.analyze(_input("我没有胸口疼"))
    assert result.level == "low"


@pytest.mark.asyncio
async def test_negated_high_keyword(engine):
    result = await engine.analyze(_input("我并没有转钱"))
    assert result.level == "low"
