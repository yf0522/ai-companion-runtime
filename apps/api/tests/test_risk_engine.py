"""Tests for the risk engine — elderly companion: health, scam, emotional."""
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
    assert "正在发送" in queued
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

    gate = await run_risk_gate("u1", "s1", "我很孤单", AsyncMock())

    assert gate.blocked is False
    assert gate.metadata["decision_persistence"]["error_code"] == "decision_persistence_failed"
    assert "error" not in gate.metadata["decision_persistence"]
    family_notify.assert_not_awaited()


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
    assert "暂时无法联系" in reply
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
    persist = AsyncMock(return_value=SimpleNamespace(assistant_message_id="assistant-1"))
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
    assert gate.metadata["audit_error"] == "TimeoutError"
    assert "120" in gate.metadata["response_text"]
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
