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
    notify = AsyncMock()
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
