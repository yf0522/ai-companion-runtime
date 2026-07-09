"""Snooze / 二次提醒 tests for ReminderTool."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.engines.intent_engine import IntentEngine
from app.engines.base import AnalyzerInput
from app.tools.reminder_tool import ReminderTool, detect_snooze


def test_detect_snooze_default_30():
    assert detect_snooze("晚点再吃") == 30
    assert detect_snooze("等会儿再吃") == 30


def test_detect_snooze_half_hour():
    assert detect_snooze("半小时后再说") == 30


def test_detect_snooze_minutes():
    assert detect_snooze("20分钟后再提醒我") == 20


def test_detect_snooze_non_match():
    assert detect_snooze("每天晚上8点提醒我吃药") is None


@pytest.mark.asyncio
async def test_intent_routes_snooze_to_reminder():
    engine = IntentEngine()
    result = await engine.analyze(
        AnalyzerInput(
            user_id="u",
            session_id="s",
            message="晚点再吃",
            trace_id="t",
        )
    )
    assert "reminder" in result.tool_needs


@pytest.mark.asyncio
async def test_execute_snooze_updates_next_fire(monkeypatch):
    tool = ReminderTool()
    next_fire = datetime.utcnow() + timedelta(minutes=30)

    async def fake_snooze(**kwargs):
        assert kwargs["snooze_minutes"] == 30
        return "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "吃降压药", next_fire

    monkeypatch.setattr(tool, "_snooze_reminder", fake_snooze)

    result = await tool.execute(
        {
            "query": "晚点再吃",
            "user_id": "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
        }
    )
    assert result.status == "success"
    assert result.data["action"] == "reminder_snooze"
    assert result.data["reminder_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert "30分钟" in result.display_text


@pytest.mark.asyncio
async def test_create_then_snooze_flow(monkeypatch):
    """Regression: evening Chinese hour create must persist before snooze works."""
    tool = ReminderTool()
    stored: dict = {}

    async def fake_persist(**kwargs):
        stored.update(kwargs)
        return "55555555-5555-5555-5555-555555555555", kwargs["remind_time"]

    async def fake_snooze(**kwargs):
        assert stored, "create should have persisted a reminder first"
        return stored.get("reminder_id", "55555555-5555-5555-5555-555555555555"), "吃降压药", next_fire

    next_fire = datetime.utcnow() + timedelta(minutes=30)
    monkeypatch.setattr(tool, "_persist_reminder", fake_persist)
    monkeypatch.setattr(tool, "_snooze_reminder", fake_snooze)

    create = await tool.execute(
        {
            "query": "提醒我晚上八点吃降压药",
            "user_id": str(uuid.uuid4()),
        }
    )
    assert create.status == "success"
    assert create.data["action"] == "reminder_create"
    stored["reminder_id"] = create.data["reminder_id"]

    snooze = await tool.execute(
        {
            "query": "晚点再吃",
            "user_id": str(uuid.uuid4()),
        }
    )
    assert snooze.status == "success"
    assert snooze.data["action"] == "reminder_snooze"
    assert "no_reminder" not in (snooze.data.get("reason") or "")


@pytest.mark.asyncio
async def test_execute_snooze_no_reminder(monkeypatch):
    tool = ReminderTool()

    async def fake_snooze(**kwargs):
        raise LookupError("no active reminder")

    monkeypatch.setattr(tool, "_snooze_reminder", fake_snooze)
    result = await tool.execute(
        {
            "query": "晚点再吃",
            "user_id": str(uuid.uuid4()),
        }
    )
    assert result.status == "failed"
    assert result.data["reason"] == "no_reminder"
