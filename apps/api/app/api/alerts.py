from __future__ import annotations

from datetime import datetime
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.auth import get_current_user_uuid

router = APIRouter(tags=["alerts"])


class ReminderItem(BaseModel):
    id: str
    user_id: str
    label: str
    timer_type: str
    repeat_mode: str
    duration_sec: int
    hour: Optional[int]
    minute: Optional[int]
    created_at: str
    status: str = "active"


class NotificationItem(BaseModel):
    id: str
    user_id: str
    category: str
    title: str
    message: str
    severity: str
    status: str = "pending"
    created_at: str


# In-memory placeholders for demo mode.
_reminders: dict[str, list[ReminderItem]] = {}
_notifications: dict[str, list[NotificationItem]] = {}


@router.get("/reminders")
async def list_reminders(user_id: uuid.UUID = Depends(get_current_user_uuid)):
    uid = str(user_id)
    now = datetime.utcnow().isoformat()
    items = _reminders.get(uid, [])
    if not items:
        items = [
            ReminderItem(
                id=str(uuid.uuid4()),
                user_id=uid,
                label="示例提醒（未接入持久化）",
                timer_type="reminder",
                repeat_mode="once",
                duration_sec=0,
                hour=None,
                minute=None,
                created_at=now,
            )
        ]
    return {
        "user_id": uid,
        "items": [item.model_dump() for item in items],
        "total": len(items),
        "status": "demo_placeholder",
    }


@router.get("/notifications")
async def list_notifications(user_id: uuid.UUID = Depends(get_current_user_uuid)):
    uid = str(user_id)
    now = datetime.utcnow().isoformat()
    items = _notifications.get(uid, [])
    if not items:
        items = [
            NotificationItem(
                id=str(uuid.uuid4()),
                user_id=uid,
                category="scam_alert",
                title="待接入的家属通知适配",
                message="当前后端仅提供占位能力：当诈骗/健康/情绪预警触发时，会输出结构化类别，可在后续接入通知提供方后发送给家属。",
                severity="medium",
                status="roadmap",
                created_at=now,
            )
        ]
    return {
        "user_id": uid,
        "items": [item.model_dump() for item in items],
        "total": len(items),
        "status": "demo_placeholder",
    }
