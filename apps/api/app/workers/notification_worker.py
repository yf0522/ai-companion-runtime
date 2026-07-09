"""Celery worker that sends risk notifications to emergency contacts via webhook."""
from __future__ import annotations

import logging
import uuid

from app.workers.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="app.workers.notification_worker.send_risk_notification")
def send_risk_notification(user_id: str, risk_level: str, risk_category: str, message_summary: str):
    import asyncio
    asyncio.run(_send_notifications(user_id, risk_level, risk_category, message_summary))


async def _send_notifications(user_id: str, risk_level: str, risk_category: str, summary: str):
    import json
    from datetime import datetime
    from app.db.session import async_session
    from app.db.models import EmergencyContact, NotificationLog, User
    from sqlalchemy import select

    db_user_id = uuid.UUID(user_id)

    async with async_session() as db:
        user_result = await db.execute(select(User.username).where(User.id == db_user_id))
        elder_name = user_result.scalar_one_or_none() or "Unknown"

        result = await db.execute(
            select(EmergencyContact).where(
                EmergencyContact.user_id == db_user_id,
                EmergencyContact.is_active == True,
            ).order_by(EmergencyContact.priority)
        )
        contacts = result.scalars().all()

        for contact in contacts:
            levels = contact.notify_on_levels or ["critical", "high"]
            if risk_level not in levels:
                continue

            status = "skipped"
            if contact.webhook_url:
                status = await _send_webhook(contact.webhook_url, {
                    "elder_name": elder_name, "user_id": user_id,
                    "risk_level": risk_level, "category": risk_category,
                    "summary": summary, "timestamp": datetime.utcnow().isoformat(),
                    "contact_name": contact.name,
                })

            log = NotificationLog(
                user_id=db_user_id, contact_id=contact.id,
                risk_level=risk_level, risk_category=risk_category,
                summary=summary, webhook_status=status,
            )
            db.add(log)

        await db.commit()


async def _send_webhook(url: str, payload: dict) -> str:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return "sent" if resp.status_code < 300 else "failed"
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return "failed"
