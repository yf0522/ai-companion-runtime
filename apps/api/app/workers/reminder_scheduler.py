"""Celery task that fires due reminders via Redis pub/sub."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from app.workers.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="app.workers.reminder_scheduler.check_due_reminders")
def check_due_reminders():
    import asyncio
    asyncio.run(_check_and_fire())


async def _check_and_fire():
    from app.db.session import async_session
    from app.db.models import Reminder, ReminderHistory
    from sqlalchemy import select

    now = datetime.utcnow()

    async with async_session() as db:
        result = await db.execute(
            select(Reminder).where(
                Reminder.is_active.is_(True),
                Reminder.next_fire_at <= now,
            )
        )
        due_reminders = result.scalars().all()

        for reminder in due_reminders:
            delivered = await _deliver_reminder(reminder)

            history = ReminderHistory(
                reminder_id=reminder.id,
                fired_at=now,
                delivered=delivered,
            )
            db.add(history)

            if reminder.schedule_type == "once":
                reminder.is_active = False
            elif reminder.schedule_type == "daily":
                reminder.next_fire_at = reminder.next_fire_at + timedelta(days=1)
            elif reminder.schedule_type == "weekly":
                reminder.next_fire_at = reminder.next_fire_at + timedelta(weeks=1)

            reminder.last_fired_at = now

        await db.commit()

    if due_reminders:
        logger.info(f"Fired {len(due_reminders)} reminders")


async def _deliver_reminder(reminder) -> bool:
    try:
        from app.storage.redis_client import get_redis

        r = await get_redis()
        payload = json.dumps({
            "type": "reminder",
            "user_id": str(reminder.user_id),
            "reminder_id": str(reminder.id),
            "title": reminder.title,
            "message": f"该{reminder.title}啦，记得按时哦",
        })
        await r.publish(f"reminder:{reminder.user_id}", payload)
        return True
    except Exception as e:
        logger.warning(f"Failed to deliver reminder {reminder.id}: {e}")
        return False
