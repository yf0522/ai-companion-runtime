"""Tests for reminder tool — schedule type detection and time parsing."""
import pytest
from datetime import time
from app.tools.reminder_tool import detect_schedule_type, parse_time_from_text


def test_daily_medicine():
    assert detect_schedule_type("吃药") == "daily"


def test_daily_blood_pressure():
    assert detect_schedule_type("量血压") == "daily"


def test_once_phone_call():
    assert detect_schedule_type("明天打电话给小李") == "once"


def test_once_buy():
    assert detect_schedule_type("买菜") == "once"


def test_unknown_returns_none():
    assert detect_schedule_type("随便什么事") is None


def test_parse_time_12_oclock():
    result = parse_time_from_text("12点")
    assert result is not None
    assert result.hour == 12
    assert result.minute == 0


def test_parse_time_afternoon():
    result = parse_time_from_text("下午3点")
    assert result is not None
    assert result.hour == 15


def test_parse_time_with_minutes():
    result = parse_time_from_text("8点30")
    assert result is not None
    assert result.hour == 8
    assert result.minute == 30
