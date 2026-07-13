"""Celery task that fires due reminders via Redis pub/sub."""
from __future__ import annotations

import json
import logging
import socket
import uuid
from datetime import datetime, timedelta

from app.workers.celery_app import app
from app.workers.async_runner import run_async_task

logger = logging.getLogger(__name__)


def build_attempt_idempotency_key(reminder_id: object, due_at: datetime, attempt_number: int) -> str:
    return f"reminder:{reminder_id}:{due_at.replace(microsecond=0).isoformat()}:{attempt_number}"


def next_delivery_state(*, delivered: bool, attempt_number: int, now: datetime) -> dict[str, object]:
    if delivered:
        return {"state": "sent", "failed_at": None, "next_fire_at": None, "is_terminal_failure": False}
    if attempt_number >= 3:
        return {"state": "failed", "failed_at": now, "next_fire_at": None, "is_terminal_failure": True}
    return {
        "state": "retry_scheduled",
        "failed_at": None,
        "next_fire_at": now + timedelta(minutes=2 * attempt_number),
        "is_terminal_failure": False,
    }


@app.task(name="app.workers.reminder_scheduler.check_due_reminders")
def check_due_reminders():
    run_async_task(_check_and_fire)


async def _check_and_fire():
    from app.db.session import async_session
    from app.db.models import Reminder, ReminderDeliveryAttempt, ReminderHistory
    from sqlalchemy import select

    now = datetime.utcnow()
    lease_owner = f"{socket.gethostname()}:{uuid.uuid4()}"
    lease_until = now + timedelta(seconds=60)

    async with async_session() as db:
        stmt = (
            select(Reminder).where(
                Reminder.is_active.is_(True),
                Reminder.next_fire_at <= now,
                (Reminder.lease_until.is_(None) | (Reminder.lease_until < now)),
            )
            .order_by(Reminder.next_fire_at.asc())
            .limit(100)
        )
        stmt = stmt.with_for_update(skip_locked=True)
        result = await db.execute(stmt)
        due_reminders = result.scalars().all()

        for reminder in due_reminders:
            reminder.lease_owner = lease_owner
            reminder.lease_until = lease_until
        await db.flush()

        for reminder in due_reminders:
            attempt_number = (reminder.retry_count or 0) + 1
            idempotency_key = build_attempt_idempotency_key(
                reminder.id, reminder.next_fire_at, attempt_number
            )
            existing_attempt = (
                await db.execute(
                    select(ReminderDeliveryAttempt.id).where(
                        ReminderDeliveryAttempt.idempotency_key == idempotency_key
                    )
                )
            ).scalar_one_or_none()
            if existing_attempt is not None:
                logger.info("Duplicate reminder attempt skipped for key=%s", idempotency_key)
                reminder.lease_owner = None
                reminder.lease_until = None
                continue
            attempt = ReminderDeliveryAttempt(
                reminder_id=reminder.id,
                user_id=reminder.user_id,
                attempt_number=attempt_number,
                state="queued",
                idempotency_key=idempotency_key,
                due_at=reminder.next_fire_at,
                lease_until=lease_until,
            )
            db.add(attempt)
            await db.flush()

            delivered = await _deliver_reminder(reminder, attempt_id=str(attempt.id))
            attempt.updated_at = datetime.utcnow()

            history = ReminderHistory(
                reminder_id=reminder.id,
                fired_at=now,
                delivered=delivered,
            )
            db.add(history)

            delivery_state = next_delivery_state(
                delivered=delivered,
                attempt_number=attempt_number,
                now=datetime.utcnow(),
            )
            if delivered:
                attempt.state = str(delivery_state["state"])
                attempt.sent_at = datetime.utcnow()
                reminder.retry_count = 0
                if reminder.schedule_type == "once":
                    reminder.is_active = False
                elif reminder.schedule_type == "daily":
                    reminder.next_fire_at = reminder.next_fire_at + timedelta(days=1)
                elif reminder.schedule_type == "weekly":
                    reminder.next_fire_at = reminder.next_fire_at + timedelta(weeks=1)
                reminder.last_fired_at = now
            else:
                reminder.retry_count = attempt_number
                if delivery_state["is_terminal_failure"]:
                    attempt.state = str(delivery_state["state"])
                    attempt.failed_at = delivery_state["failed_at"]
                    reminder.is_active = False
                else:
                    attempt.state = str(delivery_state["state"])
                    reminder.next_fire_at = delivery_state["next_fire_at"]
            reminder.lease_owner = None
            reminder.lease_until = None

        await db.commit()

    if due_reminders:
        logger.info(f"Fired {len(due_reminders)} reminders")


async def _deliver_reminder(reminder, *, attempt_id: str | None = None) -> bool:
    try:
        from app.storage.redis_client import get_redis

        r = await get_redis()
        payload = json.dumps({
            "type": "reminder",
            "user_id": str(reminder.user_id),
            "reminder_id": str(reminder.id),
            "attempt_id": attempt_id,
            "title": reminder.title,
            "message": f"该{reminder.title}啦，记得按时哦",
        })
        await r.publish(f"reminder:{reminder.user_id}", payload)
        return True
    except Exception as e:
        logger.warning(f"Failed to deliver reminder {reminder.id}: {e}")
        return False


async def reconcile_reminder_attempts() -> dict[str, int]:
    """Expire stale in-flight attempts and release stale reminder leases."""
    from app.db.models import Reminder, ReminderDeliveryAttempt
    from app.db.session import async_session
    from sqlalchemy import select

    now = datetime.utcnow()
    expired_attempts = 0
    released_leases = 0
    async with async_session() as db:
        attempts = (
            await db.execute(
                select(ReminderDeliveryAttempt).where(
                    ReminderDeliveryAttempt.state.in_(["queued", "sent", "retry_scheduled"]),
                    ReminderDeliveryAttempt.lease_until.is_not(None),
                    ReminderDeliveryAttempt.lease_until < now,
                )
            )
        ).scalars().all()
        for attempt in attempts:
            attempt.state = "expired"
            attempt.expired_at = now
            attempt.updated_at = now
            expired_attempts += 1

        reminders = (
            await db.execute(
                select(Reminder).where(
                    Reminder.lease_until.is_not(None),
                    Reminder.lease_until < now,
                )
            )
        ).scalars().all()
        for reminder in reminders:
            reminder.lease_until = None
            reminder.lease_owner = None
            released_leases += 1

        await db.commit()
    return {"expired_attempts": expired_attempts, "released_leases": released_leases}
