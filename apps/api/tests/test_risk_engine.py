"""Tests for the risk engine — bypass resistance, negation, and safe context."""
import pytest
from app.engines.base import AnalyzerInput
from app.engines.risk_engine import RiskEngine, _normalize_text


@pytest.fixture
def engine():
    return RiskEngine()


def _input(msg: str) -> AnalyzerInput:
    return AnalyzerInput(user_id="test", session_id="test", message=msg, trace_id="t1")


# --- Normalization ---

def test_normalize_removes_spaces_between_cjk():
    assert "自杀" in _normalize_text("自 杀")


def test_normalize_lowercases():
    assert "suicide" in _normalize_text("SUICIDE")


# --- Critical detection ---

@pytest.mark.asyncio
async def test_critical_keyword_hit(engine):
    result = await engine.analyze(_input("我想死"))
    assert result.level == "critical"


@pytest.mark.asyncio
async def test_critical_english(engine):
    result = await engine.analyze(_input("I want to die"))
    assert result.level in ("critical", "high")


@pytest.mark.asyncio
async def test_critical_pinyin(engine):
    result = await engine.analyze(_input("我想si"))
    assert result.level == "critical"


@pytest.mark.asyncio
async def test_critical_with_spaces(engine):
    result = await engine.analyze(_input("自 杀"))
    assert result.level == "critical"


# --- Negation suppression ---

@pytest.mark.asyncio
async def test_negated_keyword_not_triggered(engine):
    result = await engine.analyze(_input("我没有想死"))
    assert result.level == "low"


@pytest.mark.asyncio
async def test_negated_high_keyword(engine):
    result = await engine.analyze(_input("我并没有撑不下去"))
    assert result.level == "low"


# --- Safe context (false positive suppression) ---

@pytest.mark.asyncio
async def test_safe_context_dead_end(engine):
    result = await engine.analyze(_input("你去死胡同里找他"))
    assert result.level == "low"


@pytest.mark.asyncio
async def test_safe_context_crash(engine):
    result = await engine.analyze(_input("我的电脑死机了"))
    assert result.level == "low"


@pytest.mark.asyncio
async def test_safe_context_laugh(engine):
    result = await engine.analyze(_input("笑死我了"))
    assert result.level == "low"


# --- Medium detection ---

@pytest.mark.asyncio
async def test_medium_keyword(engine):
    result = await engine.analyze(_input("我感到绝望"))
    assert result.level == "medium"


# --- Low (normal messages) ---

@pytest.mark.asyncio
async def test_normal_message_is_low(engine):
    result = await engine.analyze(_input("今天天气真好"))
    assert result.level == "low"
