"""CareTask domain: state machine + persistence. Reminder = scheduling projection."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

CARE_TASK_STATUSES = frozenset(
    {"pending", "due", "done", "snoozed", "missed", "cancelled"}
)
ACTIVE_STATUSES = frozenset({"pending", "due", "snoozed"})
TERMINAL_STATUSES = frozenset({"done", "missed", "cancelled"})

# Allowed transitions: from -> to
_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"due", "done", "snoozed", "missed", "cancelled"}),
    "due": frozenset({"done", "snoozed", "missed", "cancelled"}),
    "snoozed": frozenset({"pending", "due", "done", "missed", "cancelled"}),
    "done": frozenset(),
    "missed": frozenset({"done", "cancelled"}),
    "cancelled": frozenset(),
}


class CareTaskTransitionError(ValueError):
    """Invalid CareTask state transition."""


def normalize_user_id(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except (ValueError, AttributeError, TypeError):
        return uuid.uuid5(uuid.NAMESPACE_DNS, str(user_id))


def infer_initial_status(due_at: datetime | None, now: datetime | None = None) -> str:
    now = now or datetime.utcnow()
    if due_at is not None and due_at <= now:
        return "due"
    return "pending"


def can_transition(from_status: str, to_status: str) -> bool:
    if from_status not in CARE_TASK_STATUSES or to_status not in CARE_TASK_STATUSES:
        return False
    return to_status in _TRANSITIONS.get(from_status, frozenset())


def assert_transition(from_status: str, to_status: str) -> None:
    if not can_transition(from_status, to_status):
        raise CareTaskTransitionError(f"cannot transition {from_status} → {to_status}")


def refresh_status(status: str, due_at: datetime | None, snooze_until: datetime | None, now: datetime | None = None) -> str:
    """Derive due/missed/pending from clocks without mutating terminal states."""
    now = now or datetime.utcnow()
    if status in TERMINAL_STATUSES:
        return status
    if status == "snoozed":
        if snooze_until and snooze_until <= now:
            if due_at and due_at <= now:
                return "due"
            return "pending"
        return "snoozed"
    if due_at is None:
        return status if status in ACTIVE_STATUSES else "pending"
    if due_at <= now:
        # Overdue window: still actionable as due; callers may mark missed explicitly.
        return "due"
    return "pending"


def task_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "title": row.title,
        "task_type": row.task_type,
        "status": row.status,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "snooze_until": row.snooze_until.isoformat() if row.snooze_until else None,
        "reminder_id": str(row.reminder_id) if row.reminder_id else None,
        "notes": row.notes,
        "created_by": row.created_by,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
    }


async def create_care_task(
    *,
    user_id: str,
    title: str,
    task_type: str = "medication",
    due_at: datetime | None = None,
    notes: str | None = None,
    created_by: str = "chat",
    link_reminder: bool = True,
) -> dict[str, Any]:
    from app.db.models import CareTask, Reminder
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    status = infer_initial_status(due_at, now)
    reminder_id: uuid.UUID | None = None

    async with async_session() as db:
        if link_reminder and due_at is not None:
            reminder = Reminder(
                user_id=db_user_id,
                title=title,
                description=notes or f"caretask:{task_type}",
                schedule_type="once",
                time_of_day=due_at,
                next_fire_at=due_at,
                is_active=True,
                created_by=created_by,
            )
            db.add(reminder)
            await db.flush()
            reminder_id = reminder.id

        row = CareTask(
            user_id=db_user_id,
            title=title,
            task_type=task_type,
            status=status,
            due_at=due_at,
            reminder_id=reminder_id,
            notes=notes,
            created_by=created_by,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return task_to_dict(row)


async def list_care_tasks(
    *,
    user_id: str,
    include_terminal: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.db.models import CareTask
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    async with async_session() as db:
        stmt = select(CareTask).where(CareTask.user_id == db_user_id)
        if not include_terminal:
            stmt = stmt.where(CareTask.status.in_(list(ACTIVE_STATUSES | {"missed"})))
        stmt = stmt.order_by(CareTask.due_at.asc().nullslast(), CareTask.created_at.desc()).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()
        out: list[dict[str, Any]] = []
        dirty = False
        for row in rows:
            new_status = refresh_status(row.status, row.due_at, row.snooze_until, now)
            if new_status != row.status and can_transition(row.status, new_status):
                row.status = new_status
                row.updated_at = now
                dirty = True
            out.append(task_to_dict(row))
        if dirty:
            await db.commit()
        return out


async def _get_task(db: Any, user_id: uuid.UUID, task_id: str) -> Any:
    from sqlalchemy import select

    from app.db.models import CareTask

    row = (
        await db.execute(
            select(CareTask).where(
                CareTask.id == uuid.UUID(task_id),
                CareTask.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError("care_task_not_found")
    return row


async def complete_care_task(*, user_id: str, task_id: str) -> dict[str, Any]:
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    async with async_session() as db:
        row = await _get_task(db, db_user_id, task_id)
        current = refresh_status(row.status, row.due_at, row.snooze_until, now)
        if current != row.status and can_transition(row.status, current):
            row.status = current
        assert_transition(row.status, "done")
        row.status = "done"
        row.completed_at = now
        row.updated_at = now
        row.snooze_until = None
        if row.reminder_id:
            from app.db.models import Reminder

            rem = await db.get(Reminder, row.reminder_id)
            if rem is not None:
                rem.is_active = False
        await db.commit()
        await db.refresh(row)
        return task_to_dict(row)


async def snooze_care_task(
    *,
    user_id: str,
    task_id: str | None = None,
    minutes: int = 30,
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.models import CareTask, Reminder
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    minutes = max(1, min(int(minutes), 24 * 60))
    now = datetime.utcnow()
    snooze_until = now + timedelta(minutes=minutes)

    async with async_session() as db:
        if task_id:
            row = await _get_task(db, db_user_id, task_id)
        else:
            row = (
                await db.execute(
                    select(CareTask)
                    .where(
                        CareTask.user_id == db_user_id,
                        CareTask.status.in_(list(ACTIVE_STATUSES)),
                    )
                    .order_by(CareTask.due_at.asc().nullslast(), CareTask.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                raise LookupError("no_active_care_task")

        current = refresh_status(row.status, row.due_at, row.snooze_until, now)
        if current != row.status and can_transition(row.status, current):
            row.status = current
        assert_transition(row.status, "snoozed")
        row.status = "snoozed"
        row.snooze_until = snooze_until
        row.due_at = snooze_until
        row.updated_at = now
        if row.reminder_id:
            rem = await db.get(Reminder, row.reminder_id)
            if rem is not None:
                rem.next_fire_at = snooze_until
                rem.is_active = True
        await db.commit()
        await db.refresh(row)
        data = task_to_dict(row)
        data["snooze_minutes"] = minutes
        return data


async def cancel_care_task(*, user_id: str, task_id: str) -> dict[str, Any]:
    from app.db.models import Reminder
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    async with async_session() as db:
        row = await _get_task(db, db_user_id, task_id)
        assert_transition(row.status, "cancelled")
        row.status = "cancelled"
        row.updated_at = now
        row.snooze_until = None
        if row.reminder_id:
            rem = await db.get(Reminder, row.reminder_id)
            if rem is not None:
                rem.is_active = False
        await db.commit()
        await db.refresh(row)
        return task_to_dict(row)


async def mark_missed(*, user_id: str, task_id: str) -> dict[str, Any]:
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    async with async_session() as db:
        row = await _get_task(db, db_user_id, task_id)
        current = refresh_status(row.status, row.due_at, row.snooze_until, now)
        if current != row.status and can_transition(row.status, current):
            row.status = current
        assert_transition(row.status, "missed")
        row.status = "missed"
        row.updated_at = now
        await db.commit()
        await db.refresh(row)
        return task_to_dict(row)
