"""Project CareTask / Reminder domain results into device-consumable WS payloads.

CareTask remains source of truth; Reminder is the scheduling projection.
Device events reuse the reminder_* wire shape the firmware already consumes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def infer_schedule_type_from_utterance(text: str | None) -> str:
    """Infer Reminder.schedule_type from natural language (daily vs once).

    Explicit daily markers win. Matches ReminderTool device timer rules:
    only 「每天」/「每日」 force daily; otherwise once.
    """
    if not text:
        return "once"
    if "每天" in text or "每日" in text:
        return "daily"
    return "once"


def _parse_due(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def caretask_device_create_payload(
    task: dict[str, Any],
    *,
    schedule_type: str | None = None,
    query: str | None = None,
) -> dict[str, Any] | None:
    """Build reminder_create payload from a CareTask row (requires reminder_id)."""
    reminder_id = task.get("reminder_id")
    if not reminder_id:
        return None

    st = schedule_type or task.get("schedule_type")
    if not st:
        st = infer_schedule_type_from_utterance(query)
    due = _parse_due(task.get("due_at") or task.get("snooze_until") or task.get("next_fire_at"))
    repeat_mode = "daily" if st == "daily" else "once"
    payload: dict[str, Any] = {
        "reminder_id": str(reminder_id),
        "label": task.get("title") or "提醒",
        "schedule_type": st,
        "repeat_mode": repeat_mode,
        "timer_type": "alarm",
        "caretask_id": task.get("id"),
        "next_fire_at": task.get("due_at") or task.get("snooze_until"),
    }
    if due is not None:
        payload["hour"] = due.hour
        payload["minute"] = due.minute
    return payload


def caretask_device_snooze_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    """Build reminder_snooze payload; minutes may live on outer or nested task."""
    task = data.get("task") if isinstance(data.get("task"), dict) else {}
    reminder_id = data.get("reminder_id") or task.get("reminder_id")
    if not reminder_id:
        return None
    minutes = data.get("snooze_minutes")
    if minutes is None:
        minutes = task.get("snooze_minutes")
    if minutes is None:
        minutes = 30
    return {
        "reminder_id": str(reminder_id),
        "label": data.get("label") or task.get("title"),
        "snooze_minutes": int(minutes),
        "next_fire_at": data.get("next_fire_at")
        or task.get("snooze_until")
        or task.get("due_at"),
        "caretask_id": task.get("id"),
    }


def caretask_device_cancel_payload(task: dict[str, Any]) -> dict[str, Any] | None:
    """Build reminder_cancel payload so devices can drop a local timer."""
    reminder_id = task.get("reminder_id")
    if not reminder_id:
        return None
    return {
        "reminder_id": str(reminder_id),
        "label": task.get("title"),
        "caretask_id": task.get("id"),
        "reason": task.get("status") or "cancelled",
    }
