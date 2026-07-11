"""Tests for intent engine — tool triggering and context awareness."""
import pytest
from app.engines.base import AnalyzerInput
from app.engines.intent_engine import IntentEngine


@pytest.fixture
def engine():
    return IntentEngine()


def _input(msg: str) -> AnalyzerInput:
    return AnalyzerInput(user_id="test", session_id="test", message=msg, trace_id="t1")


# --- Tool detection ---

@pytest.mark.asyncio
async def test_weather_query_triggers_tool(engine):
    result = await engine.analyze(_input("上海天气怎么样"))
    assert "utility" in result.tool_needs


@pytest.mark.asyncio
async def test_calculator_triggers_tool(engine):
    result = await engine.analyze(_input("帮我算一下 3+5"))
    assert "utility" in result.tool_needs


# --- False positive suppression ---

@pytest.mark.asyncio
async def test_weather_compliment_no_tool(engine):
    """'天气真好' is a statement, not a query — should not trigger weather tool."""
    result = await engine.analyze(_input("天气真好"))
    assert "utility" not in result.tool_needs


@pytest.mark.asyncio
async def test_weather_nice_no_tool(engine):
    result = await engine.analyze(_input("今天天气不错"))
    assert "utility" not in result.tool_needs


# --- Intent classification ---

@pytest.mark.asyncio
async def test_emotional_message_is_support(engine):
    result = await engine.analyze(_input("我好难过"))
    assert result.primary_intent == "emotional_support"


@pytest.mark.asyncio
async def test_task_with_tool_is_task(engine):
    result = await engine.analyze(_input("帮我算一下这个月花了多少 100+200+300"))
    assert result.primary_intent == "task"


@pytest.mark.asyncio
async def test_chitchat(engine):
    result = await engine.analyze(_input("你好呀"))
    assert result.primary_intent == "chitchat"


@pytest.mark.asyncio
async def test_question_with_mark(engine):
    result = await engine.analyze(_input("量子计算是什么？"))
    assert result.primary_intent == "question"


@pytest.mark.asyncio
async def test_mixed_emotion_and_tool_prioritizes_task(engine):
    """When user has tool_needs AND emotion, task should win."""
    result = await engine.analyze(_input("好烦帮我算一下 100+200"))
    assert result.primary_intent == "task"
    assert "utility" in result.tool_needs


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["提醒我吃降糖药", "帮我记一下吃降糖药", "提醒我服用降脂药"])
async def test_medication_phrasing_routes_to_caretask(engine, message):
    result = await engine.analyze(_input(message))
    assert "caretask" in result.tool_needs
    assert "reminder" not in result.tool_needs
