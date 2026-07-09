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
