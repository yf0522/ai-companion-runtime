from __future__ import annotations

import logging
import uuid

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.auth import get_current_user
from app.api.family_auth import get_managed_elder_id

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


class SafetyEscalationCreate(BaseModel):
    risk_level: str
    risk_category: str
    summary: str
    trace_id: str | None = None
    policy_version: str = "risk-rules:v1"
    action: str = "notify_family"
    evidence_ref: str | None = None
    evidence_json: dict | None = None
    confidence: float | None = None


class ProviderReceiptIn(BaseModel):
    event_type: Literal["accepted", "delivered", "read", "failed", "expired", "unknown", "unconfigured"]
    provider_message_id: str | None = None
    payload: dict | None = None
    occurred_at: datetime | None = None


class OperatorCaseUpdate(BaseModel):
    status: Literal["unstaffed", "open", "assigned", "resolved", "closed"]
    expected_state_version: int
    resolution: str | None = None


class CaseActivityCreate(BaseModel):
    activity_type: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=2000)
    metadata: dict = Field(default_factory=dict)


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


async def _get_managed_elder_id(user: dict, *, permission: str = "view_notifications") -> uuid.UUID:
    return await get_managed_elder_id(user, permission=permission)


def _require_operator(user: dict) -> uuid.UUID:
    if user.get("role") != "operator":
        raise HTTPException(status_code=403, detail="Operator role required")
    return uuid.UUID(user["sub"])


def _operator_case_json(row) -> dict:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "elder_user_id": str(row.user_id),
        "safety_decision_id": str(row.safety_decision_id) if row.safety_decision_id else None,
        "notification_outbox_id": str(row.notification_outbox_id) if row.notification_outbox_id else None,
        "status": row.status,
        "severity": row.severity,
        "owner_id": str(row.owner_id) if row.owner_id else None,
        "summary": row.summary,
        "resolution": row.resolution,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "state_version": row.state_version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "next_action": (
            "Assign an operator before handling" if row.status == "unstaffed" else None
        ),
    }


def _case_activity_json(row) -> dict:
    payload = row.payload_json or {}
    return {
        "id": str(row.id),
        "case_id": str(row.case_id),
        "actor_type": "operator" if row.actor_user_id else "system",
        "actor_id": str(row.actor_user_id) if row.actor_user_id else None,
        "activity_type": row.activity_type,
        "summary": payload.get("summary") or row.activity_type,
        "created_at": row.created_at.isoformat() if row.created_at else datetime.utcnow().isoformat(),
        "metadata": payload,
    }


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


@router.post("/safety/escalations")
async def create_safety_escalation(
    body: SafetyEscalationCreate,
    user: dict = Depends(get_current_user),
):
    elder_id = await _get_managed_elder_id(user)
    from app.workers.notification_outbox_worker import create_safety_notification_pipeline

    try:
        return await create_safety_notification_pipeline(
            user_id=str(elder_id),
            risk_level=body.risk_level,
            risk_category=body.risk_category,
            summary=body.summary,
            trace_id=body.trace_id,
            policy_version=body.policy_version,
            action=body.action,
            evidence_ref=body.evidence_ref,
            evidence_json=body.evidence_json,
            confidence=body.confidence,
        )
    except Exception as e:
        logger.error("Failed to create safety escalation: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Safety escalation could not be persisted")


@router.post("/notification-outbox/{outbox_id}/receipts")
async def record_notification_receipt(
    outbox_id: str,
    body: ProviderReceiptIn,
    user: dict = Depends(get_current_user),
):
    elder_id = await _get_managed_elder_id(user)
    from app.workers.notification_outbox_worker import record_provider_receipt

    try:
        return await record_provider_receipt(
            outbox_id=outbox_id,
            event_type=body.event_type,
            provider_message_id=body.provider_message_id,
            payload=body.payload,
            occurred_at=body.occurred_at,
            expected_user_id=elder_id,
        )
    except (LookupError, ValueError):
        raise HTTPException(status_code=404, detail="Notification outbox not found")


@router.post("/notification-outbox/webhook-receipts")
async def record_signed_notification_receipt(
    request: Request,
    x_companion_timestamp: str | None = Header(default=None, alias="X-Companion-Timestamp"),
    x_companion_signature: str | None = Header(default=None, alias="X-Companion-Signature"),
    x_companion_event_id: str | None = Header(default=None, alias="X-Companion-Event-Id"),
):
    import json

    from app.workers.notification_outbox_worker import (
        record_signed_provider_receipt,
    )

    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON receipt") from exc
    try:
        return await record_signed_provider_receipt(
            body=body,
            raw_body=raw_body,
            timestamp_header=x_companion_timestamp,
            signature_header=x_companion_signature,
            event_id=x_companion_event_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/operator/cases")
async def list_operator_cases(user: dict = Depends(get_current_user)):
    _require_operator(user)
    from app.db.models import OperatorCase
    from app.db.session import async_session

    async with async_session() as db:
        rows = (
            await db.execute(
                select(OperatorCase)
                .where(OperatorCase.status.in_(["unstaffed", "open", "assigned"]))
                .order_by(OperatorCase.created_at.asc())
                .limit(100)
            )
        ).scalars().all()
    return {
        "items": [_operator_case_json(row) for row in rows],
        "total": len(rows),
    }


@router.get("/operator/cases/{case_id}")
async def get_operator_case(case_id: uuid.UUID, user: dict = Depends(get_current_user)):
    _require_operator(user)
    from app.db.models import OperatorCase
    from app.db.session import async_session

    async with async_session() as db:
        row = await db.get(OperatorCase, case_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Operator case not found")
    return _operator_case_json(row)


@router.get("/operator/cases/{case_id}/activities")
async def list_operator_case_activities(case_id: uuid.UUID, user: dict = Depends(get_current_user)):
    _require_operator(user)
    from app.db.models import CaseActivity, OperatorCase
    from app.db.session import async_session

    async with async_session() as db:
        case = await db.get(OperatorCase, case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Operator case not found")
        rows = (
            await db.execute(
                select(CaseActivity)
                .where(CaseActivity.case_id == case_id)
                .order_by(CaseActivity.created_at.asc())
            )
        ).scalars().all()
    return {"items": [_case_activity_json(row) for row in rows], "total": len(rows)}


@router.post("/operator/cases/{case_id}/activities")
async def create_operator_case_activity(
    case_id: uuid.UUID,
    body: CaseActivityCreate,
    user: dict = Depends(get_current_user),
):
    operator_id = _require_operator(user)
    from app.db.models import CaseActivity, OperatorCase
    from app.db.session import async_session

    async with async_session() as db:
        case = await db.get(OperatorCase, case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Operator case not found")
        if case.status == "unstaffed" or case.owner_id != operator_id:
            raise HTTPException(status_code=409, detail="Assign this case to yourself before adding activity")
        activity = CaseActivity(
            case_id=case_id,
            actor_user_id=operator_id,
            activity_type=body.activity_type,
            payload_json={"summary": body.summary, **body.metadata},
        )
        db.add(activity)
        await db.commit()
        await db.refresh(activity)
    return _case_activity_json(activity)


@router.patch("/operator/cases/{case_id}")
async def update_operator_case(
    case_id: str,
    body: OperatorCaseUpdate,
    user: dict = Depends(get_current_user),
):
    operator_id = _require_operator(user)
    try:
        cid = uuid.UUID(case_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Operator case not found")

    from app.db.models import CaseActivity, OperatorCase
    from app.db.session import async_session

    now = datetime.utcnow()
    allowed = {
        "unstaffed": {"assigned"},
        "open": {"assigned", "closed"},
        "assigned": {"resolved", "closed"},
        "resolved": {"open", "closed"},
        "closed": set(),
    }
    async with async_session() as db:
        row = (
            await db.execute(select(OperatorCase).where(OperatorCase.id == cid).with_for_update())
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Operator case not found")
        if row.state_version != body.expected_state_version:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "stale_case_version",
                    "expected_state_version": body.expected_state_version,
                    "current_state_version": row.state_version,
                },
            )
        if row.owner_id is not None and row.owner_id != operator_id:
            raise HTTPException(status_code=409, detail="Operator case is owned by another operator")
        if body.status not in allowed.get(row.status, set()):
            raise HTTPException(
                status_code=409,
                detail={"code": "invalid_case_transition", "from": row.status, "to": body.status},
            )
        previous = row.status
        row.status = body.status
        row.owner_id = operator_id
        row.resolution = body.resolution
        row.updated_at = now
        row.state_version = (row.state_version or 1) + 1
        if body.status == "assigned":
            row.assigned_at = now
        if body.status in {"resolved", "closed"}:
            row.resolved_at = now
        if previous == "resolved" and body.status == "open":
            row.reopened_at = now
            row.resolved_at = None
        db.add(
            CaseActivity(
                case_id=row.id,
                actor_user_id=operator_id,
                activity_type="state_transition",
                from_status=previous,
                to_status=body.status,
                payload_json={"resolution": body.resolution},
            )
        )
        await db.commit()
        await db.refresh(row)
        return {
            "id": str(row.id),
            "status": row.status,
            "state_version": row.state_version,
            "owner_id": str(row.owner_id) if row.owner_id else None,
            "resolution": row.resolution,
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        }


@router.post("/operator/cases/{case_id}/transition")
async def transition_operator_case(
    case_id: str,
    body: OperatorCaseUpdate,
    user: dict = Depends(get_current_user),
):
    return await update_operator_case(case_id, body, user)
