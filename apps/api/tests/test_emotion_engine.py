"""Tests for emotion engine — negation handling and safe context."""
import pytest
from app.engines.base import AnalyzerInput
from app.engines.emotion_engine import EmotionEngine


@pytest.fixture
def engine():
    return EmotionEngine()


def _input(msg: str) -> AnalyzerInput:
    return AnalyzerInput(user_id="test", session_id="test", message=msg, trace_id="t1")


# --- Basic emotion detection ---

@pytest.mark.asyncio
async def test_sadness_detected(engine):
    result = await engine.analyze(_input("我好难过"))
    assert result.emotion == "sadness"


@pytest.mark.asyncio
async def test_joy_detected(engine):
    result = await engine.analyze(_input("太开心了"))
    assert result.emotion == "joy"


@pytest.mark.asyncio
async def test_anger_detected(engine):
    result = await engine.analyze(_input("气死了"))
    assert result.emotion == "anger"


@pytest.mark.asyncio
async def test_neutral_message(engine):
    result = await engine.analyze(_input("明天有什么安排"))
    assert result.emotion == "neutral"


# --- Negation handling ---

@pytest.mark.asyncio
async def test_negated_anger(engine):
    result = await engine.analyze(_input("我不生气"))
    assert result.emotion == "neutral"


@pytest.mark.asyncio
async def test_negated_sadness(engine):
    result = await engine.analyze(_input("我没有难过"))
    assert result.emotion == "neutral"


# --- Safe context ---

@pytest.mark.asyncio
async def test_polite_request_not_anger(engine):
    """'麻烦你帮我' contains '烦' but should not match anger."""
    result = await engine.analyze(_input("麻烦你帮我查一下"))
    assert result.emotion == "neutral"


# --- Intensity modifiers ---

@pytest.mark.asyncio
async def test_booster_increases_intensity(engine):
    base = await engine.analyze(_input("我难过"))
    boosted = await engine.analyze(_input("我非常难过"))
    assert boosted.intensity > base.intensity


@pytest.mark.asyncio
async def test_dampener_decreases_intensity(engine):
    base = await engine.analyze(_input("我难过"))
    dampened = await engine.analyze(_input("我有点难过"))
    assert dampened.intensity < base.intensity
