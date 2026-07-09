"""Family reminder management and notification history endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.auth import get_current_user

router = APIRouter(tags=["reminders"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ReminderCreate(BaseModel):
    title: str
    time_of_day: str  # "HH:MM"
    schedule_type: str  # daily / weekly / once / interval
    description: Optional[str] = None


class ReminderUpdate(BaseModel):
    title: Optional[str] = None
    time_of_day: Optional[str] = None
    schedule_type: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ReminderAttemptReceipt(BaseModel):
    state: Literal["device_received", "played", "acknowledged", "failed", "expired"]
    provider_message_id: str | None = None
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_managed_elder_id(user: dict, *, permission: str) -> uuid.UUID:
    """Resolve the elder user_id this user manages.

    - elder role -> own user_id
    - family role -> look up FamilyBinding
    """
    role = user.get("role", "elder")
    user_id = uuid.UUID(user["sub"])

    if role == "elder":
        return user_id

    if role == "family":
        from app.db.session import async_session
        from app.db.models import FamilyBinding

        async with async_session() as db:
            result = await db.execute(
                select(FamilyBinding)
                .where(FamilyBinding.family_user_id == user_id)
                .order_by(FamilyBinding.created_at.desc())
                .limit(1)
            )
            binding = result.scalar_one_or_none()
            if not binding:
                raise HTTPException(status_code=403, detail="No elder binding found for this family account")
            if permission not in set(binding.permissions or []):
                raise HTTPException(status_code=403, detail="Family account lacks reminder permission")
            return binding.elder_user_id

    raise HTTPException(status_code=403, detail="Unknown role")


def _parse_time_of_day(value: str) -> datetime:
    """Parse 'HH:MM' into a datetime with today's date."""
    parts = value.split(":")
    h, m = int(parts[0]), int(parts[1])
    now = datetime.utcnow()
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/reminders")
async def list_reminders(user: dict = Depends(get_current_user)):
    elder_id = await _get_managed_elder_id(user, permission="view_reminders")

    from app.db.session import async_session
    from app.db.models import Reminder

    async with async_session() as db:
        result = await db.execute(
            select(Reminder).where(Reminder.user_id == elder_id).order_by(Reminder.created_at.desc())
        )
        reminders = result.scalars().all()
        return [
            {
                "id": str(r.id),
                "title": r.title,
                "description": r.description,
                "schedule_type": r.schedule_type,
                "time_of_day": r.time_of_day.strftime("%H:%M") if r.time_of_day else None,
                "next_fire_at": r.next_fire_at.isoformat() if r.next_fire_at else None,
                "is_active": r.is_active,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reminders
        ]


@router.post("/reminders")
async def create_reminder(body: ReminderCreate, user: dict = Depends(get_current_user)):
    elder_id = await _get_managed_elder_id(user, permission="manage_reminders")
    role = user.get("role", "elder")

    from app.db.session import async_session
    from app.db.models import Reminder

    time_dt = _parse_time_of_day(body.time_of_day)
    next_fire = time_dt
    if next_fire < datetime.utcnow():
        from datetime import timedelta
        next_fire = next_fire + timedelta(days=1)

    async with async_session() as db:
        reminder = Reminder(
            user_id=elder_id,
            title=body.title,
            description=body.description,
            schedule_type=body.schedule_type,
            time_of_day=time_dt,
            next_fire_at=next_fire,
            created_by=role,
        )
        db.add(reminder)
        await db.commit()
        await db.refresh(reminder)
        return {
            "id": str(reminder.id),
            "title": reminder.title,
            "schedule_type": reminder.schedule_type,
            "next_fire_at": reminder.next_fire_at.isoformat() if reminder.next_fire_at else None,
        }


@router.put("/reminders/{reminder_id}")
async def update_reminder(reminder_id: str, body: ReminderUpdate, user: dict = Depends(get_current_user)):
    elder_id = await _get_managed_elder_id(user, permission="manage_reminders")

    from app.db.session import async_session
    from app.db.models import Reminder

    async with async_session() as db:
        result = await db.execute(
            select(Reminder).where(Reminder.id == uuid.UUID(reminder_id), Reminder.user_id == elder_id)
        )
        reminder = result.scalar_one_or_none()
        if not reminder:
            raise HTTPException(status_code=404, detail="Reminder not found")

        if body.title is not None:
            reminder.title = body.title
        if body.description is not None:
            reminder.description = body.description
        if body.schedule_type is not None:
            reminder.schedule_type = body.schedule_type
        if body.time_of_day is not None:
            reminder.time_of_day = _parse_time_of_day(body.time_of_day)
            reminder.next_fire_at = reminder.time_of_day
        if body.is_active is not None:
            reminder.is_active = body.is_active

        await db.commit()
        await db.refresh(reminder)
        return {
            "id": str(reminder.id),
            "title": reminder.title,
            "schedule_type": reminder.schedule_type,
            "is_active": reminder.is_active,
        }


@router.delete("/reminders/{reminder_id}")
async def delete_reminder(reminder_id: str, user: dict = Depends(get_current_user)):
    elder_id = await _get_managed_elder_id(user, permission="manage_reminders")

    from app.db.session import async_session
    from app.db.models import Reminder

    async with async_session() as db:
        result = await db.execute(
            select(Reminder).where(Reminder.id == uuid.UUID(reminder_id), Reminder.user_id == elder_id)
        )
        reminder = result.scalar_one_or_none()
        if not reminder:
            raise HTTPException(status_code=404, detail="Reminder not found")

        await db.delete(reminder)
        await db.commit()
        return {"deleted": True}


@router.get("/reminders/{reminder_id}/history")
async def get_reminder_history(reminder_id: str, user: dict = Depends(get_current_user)):
    elder_id = await _get_managed_elder_id(user, permission="manage_reminders")

    from app.db.session import async_session
    from app.db.models import Reminder, ReminderHistory

    async with async_session() as db:
        # Verify ownership
        result = await db.execute(
            select(Reminder).where(Reminder.id == uuid.UUID(reminder_id), Reminder.user_id == elder_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Reminder not found")

        hist_result = await db.execute(
            select(ReminderHistory)
            .where(ReminderHistory.reminder_id == uuid.UUID(reminder_id))
            .order_by(ReminderHistory.fired_at.desc())
        )
        history = hist_result.scalars().all()
        return [
            {
                "id": str(h.id),
                "fired_at": h.fired_at.isoformat() if h.fired_at else None,
                "delivered": h.delivered,
                "acknowledged": h.acknowledged,
            }
            for h in history
        ]


@router.get("/reminders/{reminder_id}/attempts")
async def get_reminder_attempts(reminder_id: str, user: dict = Depends(get_current_user)):
    elder_id = await _get_managed_elder_id(user, permission="view_reminders")

    try:
        rid = uuid.UUID(reminder_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Reminder not found")

    from app.db.session import async_session
    from app.db.models import Reminder, ReminderDeliveryAttempt

    async with async_session() as db:
        result = await db.execute(
            select(Reminder).where(Reminder.id == rid, Reminder.user_id == elder_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Reminder not found")

        attempts = (
            await db.execute(
                select(ReminderDeliveryAttempt)
                .where(ReminderDeliveryAttempt.reminder_id == rid)
                .order_by(ReminderDeliveryAttempt.created_at.desc())
                .limit(50)
            )
        ).scalars().all()
        return [
            {
                "id": str(attempt.id),
                "reminder_id": str(attempt.reminder_id),
                "state": attempt.state,
                "attempt_number": attempt.attempt_number,
                "due_at": attempt.due_at.isoformat() if attempt.due_at else None,
                "sent_at": attempt.sent_at.isoformat() if attempt.sent_at else None,
                "device_received_at": attempt.device_received_at.isoformat() if attempt.device_received_at else None,
                "played_at": attempt.played_at.isoformat() if attempt.played_at else None,
                "acknowledged_at": attempt.acknowledged_at.isoformat() if attempt.acknowledged_at else None,
                "failed_at": attempt.failed_at.isoformat() if attempt.failed_at else None,
                "expired_at": attempt.expired_at.isoformat() if attempt.expired_at else None,
                "error_message": attempt.error_message,
            }
            for attempt in attempts
        ]


@router.post("/reminder-attempts/{attempt_id}/receipt")
async def record_reminder_attempt_receipt(
    attempt_id: str,
    body: ReminderAttemptReceipt,
    user: dict = Depends(get_current_user),
):
    elder_id = await _get_managed_elder_id(user, permission="manage_reminders")

    try:
        aid = uuid.UUID(attempt_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Reminder attempt not found")

    from app.db.session import async_session
    from app.db.models import ReminderDeliveryAttempt

    now = datetime.utcnow()
    async with async_session() as db:
        attempt = (
            await db.execute(
                select(ReminderDeliveryAttempt).where(
                    ReminderDeliveryAttempt.id == aid,
                    ReminderDeliveryAttempt.user_id == elder_id,
                )
            )
        ).scalar_one_or_none()
        if not attempt:
            raise HTTPException(status_code=404, detail="Reminder attempt not found")

        attempt.provider_message_id = body.provider_message_id or attempt.provider_message_id
        attempt.error_message = body.error_message
        attempt.state = body.state
        attempt.updated_at = now
        if body.state == "device_received":
            attempt.device_received_at = now
        elif body.state == "played":
            attempt.played_at = now
        elif body.state == "acknowledged":
            attempt.acknowledged_at = now
        elif body.state == "failed":
            attempt.failed_at = now
        elif body.state == "expired":
            attempt.expired_at = now
        await db.commit()
        await db.refresh(attempt)
        return {
            "id": str(attempt.id),
            "state": attempt.state,
            "provider_message_id": attempt.provider_message_id,
        }


@router.post("/reminders/{reminder_id}/ack")
async def acknowledge_reminder(reminder_id: str, user: dict = Depends(get_current_user)):
    """Confirm a reminder was handled (e.g. medicine taken)."""
    elder_id = await _get_managed_elder_id(user, permission="manage_reminders")

    try:
        rid = uuid.UUID(reminder_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Reminder not found")

    from app.db.session import async_session
    from app.db.models import Reminder, ReminderHistory

    async with async_session() as db:
        result = await db.execute(
            select(Reminder).where(Reminder.id == rid, Reminder.user_id == elder_id)
        )
        reminder = result.scalar_one_or_none()
        if not reminder:
            raise HTTPException(status_code=404, detail="Reminder not found")

        hist_result = await db.execute(
            select(ReminderHistory)
            .where(
                ReminderHistory.reminder_id == rid,
                ReminderHistory.acknowledged.is_(False),
            )
            .order_by(ReminderHistory.fired_at.desc())
            .limit(1)
        )
        history = hist_result.scalar_one_or_none()
        if history:
            history.acknowledged = True
            history.delivered = True
        else:
            history = ReminderHistory(
                reminder_id=rid,
                fired_at=datetime.utcnow(),
                delivered=True,
                acknowledged=True,
            )
            db.add(history)

        await db.commit()
        await db.refresh(history)
        return {
            "status": "acknowledged",
            "reminder_id": str(rid),
            "history_id": str(history.id),
            "acknowledged": True,
        }
