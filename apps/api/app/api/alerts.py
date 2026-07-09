from __future__ import annotations

import logging
import uuid

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["alerts"])


class NotificationItem(BaseModel):
    id: str
    user_id: str
    category: str
    title: str
    message: str
    trace_id: str | None = None
    severity: str
    status: str = "pending"
    created_at: str


def _notification_title(level: str, category: str | None) -> str:
    if category == "scam_alert":
        return "诈骗风险告警"
    if category == "health_emergency":
        return "健康风险告警"
    if category == "emotional_low":
        return "情绪低落告警"
    return {
        "high": "风险告警",
        "critical": "高风险告警",
        "medium": "中风险告警",
        "low": "普通风险",
    }.get(level, "风险告警")


async def _get_managed_elder_id(user: dict) -> uuid.UUID:
    role = user.get("role", "elder")
    user_id = uuid.UUID(user["sub"])

    if role == "elder":
        return user_id

    if role == "family":
        from app.db.session import async_session
        from app.db.models import FamilyBinding

        async with async_session() as db:
            result = await db.execute(
                select(FamilyBinding.elder_user_id)
                .where(FamilyBinding.family_user_id == user_id)
                .order_by(FamilyBinding.created_at.desc())
                .limit(1)
            )
            elder_id = result.scalar_one_or_none()
            if not elder_id:
                raise HTTPException(
                    status_code=403,
                    detail="No elder binding found for this family account",
                )
            return elder_id

    raise HTTPException(status_code=403, detail="Unknown role")


@router.get("/notifications")
async def list_notifications(user: dict = Depends(get_current_user)):
    elder_id = await _get_managed_elder_id(user)
    uid = str(elder_id)

    try:
        from app.db.session import async_session
        from app.db.models import NotificationLog

        async with async_session() as db:
            result = await db.execute(
                select(NotificationLog)
                .where(NotificationLog.user_id == elder_id)
                .order_by(NotificationLog.created_at.desc())
                .limit(50)
            )
            logs = result.scalars().all()
    except Exception as e:
        logger.warning(f"Failed to read NotificationLog for user={uid}: {e}")
        return {
            "user_id": uid,
            "items": [],
            "total": 0,
            "status": "unavailable",
        }

    items = [
        NotificationItem(
            id=str(log.id),
            user_id=uid,
            category=log.risk_category or "none",
            trace_id=log.trace_id,
            title=_notification_title(log.risk_level, log.risk_category),
            message=log.summary or "风险事件已生成通知记录",
            severity=log.risk_level,
            status=log.webhook_status or "pending",
            created_at=log.created_at.isoformat() if log.created_at else datetime.utcnow().isoformat(),
        ).model_dump()
        for log in logs
    ]

    return {
        "user_id": uid,
        "items": items,
        "total": len(items),
        "status": "persisted",
    }


@router.post("/notifications/{notification_id}/ack")
async def acknowledge_notification(
    notification_id: str,
    user: dict = Depends(get_current_user),
):
    """Family/elder confirmation task: mark a risk notification as acknowledged."""
    elder_id = await _get_managed_elder_id(user)

    try:
        nid = uuid.UUID(notification_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Notification not found")

    from app.db.session import async_session
    from app.db.models import NotificationLog

    async with async_session() as db:
        result = await db.execute(
            select(NotificationLog).where(
                NotificationLog.id == nid,
                NotificationLog.user_id == elder_id,
            )
        )
        log = result.scalar_one_or_none()
        if not log:
            raise HTTPException(status_code=404, detail="Notification not found")

        log.webhook_status = "acknowledged"
        await db.commit()
        await db.refresh(log)

        item = NotificationItem(
            id=str(log.id),
            user_id=str(elder_id),
            category=log.risk_category or "none",
            trace_id=log.trace_id,
            title=_notification_title(log.risk_level, log.risk_category),
            message=log.summary or "风险事件已生成通知记录",
            severity=log.risk_level,
            status=log.webhook_status or "acknowledged",
            created_at=log.created_at.isoformat() if log.created_at else datetime.utcnow().isoformat(),
        ).model_dump()

    return {"status": "acknowledged", "item": item}
