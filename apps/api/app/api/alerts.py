from __future__ import annotations

import logging
import uuid

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

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
    acknowledged_at: str | None = None
    acknowledged_by: str | None = None
    owner_id: str | None = None
    delivery_status: str | None = None
    delivery_events: list[dict] = Field(default_factory=list)
    receipts: list[dict] = Field(default_factory=list)
    evidence_href: str | None = None
    delivery: dict = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)


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
    activity_type: Literal["operator_note", "contact_attempt", "handoff"]
    summary: str = Field(min_length=1, max_length=2000)
    metadata: dict = Field(default_factory=dict)


def _notification_title(level: str, category: str | None) -> str:
    if category == "family_contact_request":
        return "长者请求联系"
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


CASE_TRANSITIONS: dict[str, set[str]] = {
    "unstaffed": {"assigned"},
    "open": {"assigned", "closed"},
    "assigned": {"resolved", "closed"},
    "resolved": {"open", "closed"},
    "closed": set(),
}

OPERATOR_ACTIVITY_TYPES = {
    "operator_note",
    "contact_attempt",
    "handoff",
    "state_transition",
    "trace_viewed",
}
RESERVED_ACTIVITY_METADATA = {"actor_type", "summary"}


def _operator_case_json(
    row,
    *,
    actor_id: uuid.UUID | None = None,
    household_id: uuid.UUID | None = None,
    decision=None,
    outbox=None,
) -> dict:
    owned_by_other = bool(row.owner_id and actor_id and row.owner_id != actor_id)
    allowed_transitions = [] if owned_by_other else sorted(CASE_TRANSITIONS.get(row.status, set()))
    trace_id = getattr(decision, "trace_id", None)
    if trace_id is None and outbox is not None:
        trace_id = (outbox.payload_json or {}).get("trace_id")
    evidence = {
        "safety_decision": {
            "id": str(row.safety_decision_id) if row.safety_decision_id else None,
            "trace_id": trace_id,
            "policy_version": getattr(decision, "policy_version", None),
            "risk_category": getattr(decision, "risk_category", None),
            "action": getattr(decision, "action", None),
            "confidence": getattr(decision, "confidence", None),
            "calibration": getattr(decision, "calibration", None),
            "evidence_ref": getattr(decision, "evidence_ref", None),
        },
        "notification_delivery": {
            "outbox_id": str(row.notification_outbox_id) if row.notification_outbox_id else None,
            "state": getattr(outbox, "state", None),
            "provider": getattr(outbox, "provider", None),
            "channel": getattr(outbox, "channel", None),
            "attempt_count": getattr(outbox, "attempt_count", None),
            "last_error": getattr(outbox, "last_error", None),
            "updated_at": (
                outbox.updated_at.isoformat()
                if outbox is not None and getattr(outbox, "updated_at", None)
                else None
            ),
        },
    }
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "elder_user_id": str(row.user_id),
        "household_id": str(household_id) if household_id else None,
        "safety_decision_id": str(row.safety_decision_id) if row.safety_decision_id else None,
        "notification_outbox_id": str(row.notification_outbox_id) if row.notification_outbox_id else None,
        "status": row.status,
        "severity": row.severity,
        "owner_id": str(row.owner_id) if row.owner_id else None,
        "ownership_status": (
            "unassigned"
            if row.owner_id is None
            else "owned_by_me"
            if actor_id and row.owner_id == actor_id
            else "owned_by_other"
        ),
        "allowed_transitions": allowed_transitions,
        "can_add_activity": bool(
            actor_id and row.owner_id == actor_id and row.status != "unstaffed"
        ),
        "summary": row.summary,
        "resolution": row.resolution,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "state_version": row.state_version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "trace_id": trace_id,
        "evidence": evidence,
        "next_action": (
            "Assign an operator before handling" if row.status == "unstaffed" else None
        ),
    }


def _case_activity_json(row) -> dict:
    payload = row.payload_json or {}
    actor_type = (
        "operator"
        if row.activity_type in OPERATOR_ACTIVITY_TYPES
        else payload.get("actor_type") or ("operator" if row.actor_user_id else "system")
    )
    return {
        "id": str(row.id),
        "case_id": str(row.case_id),
        "actor_type": actor_type,
        "actor_id": str(row.actor_user_id) if row.actor_user_id else None,
        "activity_type": row.activity_type,
        "from_status": row.from_status,
        "to_status": row.to_status,
        "summary": payload.get("summary") or row.activity_type,
        "created_at": row.created_at.isoformat() if row.created_at else datetime.utcnow().isoformat(),
        "metadata": payload,
    }


async def _load_case_contexts(db, rows) -> tuple[dict, dict, dict]:
    from app.db.models import Household, NotificationOutbox, SafetyDecision

    user_ids = {row.user_id for row in rows}
    decision_ids = {row.safety_decision_id for row in rows if row.safety_decision_id}
    outbox_ids = {row.notification_outbox_id for row in rows if row.notification_outbox_id}
    households = {}
    decisions = {}
    outboxes = {}
    if user_ids:
        found = (
            await db.execute(select(Household).where(Household.elder_user_id.in_(user_ids)))
        ).scalars().all()
        households = {row.elder_user_id: row.id for row in found}
    if decision_ids:
        found = (
            await db.execute(select(SafetyDecision).where(SafetyDecision.id.in_(decision_ids)))
        ).scalars().all()
        decisions = {row.id: row for row in found}
    if outbox_ids:
        found = (
            await db.execute(select(NotificationOutbox).where(NotificationOutbox.id.in_(outbox_ids)))
        ).scalars().all()
        outboxes = {row.id: row for row in found}
    return households, decisions, outboxes


async def _load_notification_contexts(db, logs) -> dict[str, dict]:
    from app.db.models import (
        CaseActivity,
        NotificationOutbox,
        NotificationReceipt,
        OperatorCase,
    )

    outbox_ids = {log.outbox_id for log in logs if log.outbox_id}
    decision_ids = {log.safety_decision_id for log in logs if log.safety_decision_id}
    if not outbox_ids and not decision_ids:
        return {}

    outboxes = {}
    if outbox_ids:
        rows = (
            await db.execute(select(NotificationOutbox).where(NotificationOutbox.id.in_(outbox_ids)))
        ).scalars().all()
        outboxes = {row.id: row for row in rows}

    receipts = []
    if outbox_ids:
        receipts = (
            await db.execute(
                select(NotificationReceipt)
                .where(NotificationReceipt.outbox_id.in_(outbox_ids))
                .order_by(NotificationReceipt.occurred_at.desc())
            )
        ).scalars().all()
    receipts_by_outbox: dict[uuid.UUID, list] = {}
    for receipt in receipts:
        receipts_by_outbox.setdefault(receipt.outbox_id, []).append(receipt)

    case_conditions = []
    if outbox_ids:
        case_conditions.append(OperatorCase.notification_outbox_id.in_(outbox_ids))
    if decision_ids:
        case_conditions.append(OperatorCase.safety_decision_id.in_(decision_ids))
    case_query = select(OperatorCase).where(or_(*case_conditions))
    cases = (await db.execute(case_query)).scalars().all()
    case_by_outbox = {
        row.notification_outbox_id: row for row in cases if row.notification_outbox_id
    }
    case_by_decision = {row.safety_decision_id: row for row in cases if row.safety_decision_id}

    activities = []
    case_ids = {row.id for row in cases}
    if case_ids:
        activities = (
            await db.execute(
                select(CaseActivity)
                .where(
                    CaseActivity.case_id.in_(case_ids),
                    CaseActivity.activity_type == "notification_acknowledged",
                )
                .order_by(CaseActivity.created_at.desc())
            )
        ).scalars().all()
    activity_by_notification = {}
    for activity in activities:
        notification_id = str((activity.payload_json or {}).get("notification_id") or "")
        if notification_id and notification_id not in activity_by_notification:
            activity_by_notification[notification_id] = activity

    contexts: dict[str, dict] = {}
    for log in logs:
        case = case_by_outbox.get(log.outbox_id) or case_by_decision.get(log.safety_decision_id)
        activity = activity_by_notification.get(str(log.id))
        contexts[str(log.id)] = {
            "case": case,
            "outbox": outboxes.get(log.outbox_id),
            "receipts": receipts_by_outbox.get(log.outbox_id, []),
            "ack_activity": activity,
        }
    return contexts


def _notification_item_json(log, *, user_id: uuid.UUID, context: dict | None = None) -> dict:
    context = context or {}
    case = context.get("case")
    outbox = context.get("outbox")
    receipts = context.get("receipts") or []
    activity = context.get("ack_activity")
    payload = (activity.payload_json or {}) if activity is not None else {}
    acknowledged_at = (
        activity.created_at
        if activity is not None and activity.created_at
        else getattr(log, "acknowledged_at", None)
    )
    acknowledged_by = (
        activity.actor_user_id
        if activity is not None and activity.actor_user_id
        else getattr(log, "acknowledged_by_user_id", None)
    )
    acknowledgement_actor_role = payload.get("actor_type") or getattr(
        log, "acknowledgement_actor_role", None
    )
    legacy_acknowledged = log.webhook_status == "acknowledged"
    is_acknowledged = acknowledged_at is not None or legacy_acknowledged
    log_delivery_status = None if legacy_acknowledged else log.webhook_status
    delivery_events = [
        {
            "id": str(receipt.id),
            "event_type": receipt.event_type,
            "status": receipt.event_type,
            "occurred_at": receipt.occurred_at.isoformat() if receipt.occurred_at else None,
            "created_at": receipt.created_at.isoformat() if receipt.created_at else None,
        }
        for receipt in receipts
    ]
    delivery_status = (
        delivery_events[0]["status"]
        if delivery_events
        else getattr(outbox, "state", None) or log_delivery_status
    )
    return NotificationItem(
        id=str(log.id),
        user_id=str(user_id),
        category=log.risk_category or "none",
        trace_id=log.trace_id,
        title=_notification_title(log.risk_level, log.risk_category),
        message=log.summary or "风险事件已生成通知记录",
        severity=log.risk_level,
        status="acknowledged" if is_acknowledged else log.webhook_status or "pending",
        created_at=log.created_at.isoformat() if log.created_at else datetime.utcnow().isoformat(),
        acknowledged_at=acknowledged_at.isoformat() if acknowledged_at else None,
        acknowledged_by=str(acknowledged_by) if acknowledged_by else None,
        owner_id=str(case.owner_id) if case is not None and case.owner_id else None,
        delivery_status=delivery_status,
        delivery_events=delivery_events,
        receipts=delivery_events,
        evidence_href=None,
        delivery={
            "outbox_id": str(log.outbox_id) if log.outbox_id else None,
            "state": getattr(outbox, "state", None) or log_delivery_status,
            "provider": getattr(outbox, "provider", None),
            "channel": getattr(outbox, "channel", None),
            "attempt_count": getattr(outbox, "attempt_count", None),
            "last_error": getattr(outbox, "last_error", None),
            "latest_receipt": delivery_events[0] if delivery_events else None,
        },
        evidence={
            "operator_case_id": str(case.id) if case is not None else None,
            "safety_decision_id": (
                str(log.safety_decision_id) if log.safety_decision_id else None
            ),
            "trace_id": log.trace_id,
            "ack_actor_type": acknowledgement_actor_role,
        },
    ).model_dump()


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
            contexts = await _load_notification_contexts(db, logs)
    except Exception as e:
        logger.warning(f"Failed to read NotificationLog for user={uid}: {e}")
        return {
            "user_id": uid,
            "items": [],
            "total": 0,
            "status": "unavailable",
        }

    items = [
        _notification_item_json(log, user_id=elder_id, context=contexts.get(str(log.id)))
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
    actor_id = uuid.UUID(user["sub"])
    actor_role = str(user.get("role") or "elder")

    try:
        nid = uuid.UUID(notification_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Notification not found")

    from app.db.session import async_session
    from app.db.models import CaseActivity, OperatorCase

    async with async_session() as db:
        result = await db.execute(_notification_ack_statement(nid, elder_id))
        log = result.scalar_one_or_none()
        if not log:
            raise HTTPException(status_code=404, detail="Notification not found")

        was_acknowledged = bool(getattr(log, "acknowledged_at", None)) or (
            log.webhook_status == "acknowledged"
        )
        linked_case = None
        if log.outbox_id is not None:
            linked_case = (
                await db.execute(
                    select(OperatorCase).where(
                        OperatorCase.notification_outbox_id == log.outbox_id
                    )
                )
            ).scalar_one_or_none()
        elif log.safety_decision_id is not None:
            linked_case = (
                await db.execute(
                    select(OperatorCase)
                    .where(OperatorCase.safety_decision_id == log.safety_decision_id)
                    .order_by(OperatorCase.created_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()

        acknowledgement_activity = None
        if linked_case is not None and was_acknowledged:
            prior_activities = (
                await db.execute(
                    select(CaseActivity)
                    .where(
                        CaseActivity.case_id == linked_case.id,
                        CaseActivity.activity_type == "notification_acknowledged",
                    )
                    .order_by(CaseActivity.created_at.desc())
                    .limit(50)
                )
            ).scalars().all()
            acknowledgement_activity = next(
                (
                    activity
                    for activity in prior_activities
                    if str((activity.payload_json or {}).get("notification_id")) == str(log.id)
                ),
                None,
            )
        if linked_case is not None and acknowledgement_activity is None:
            actor_label = "家属" if actor_role == "family" else "长者" if actor_role == "elder" else "用户"
            acknowledgement_activity = CaseActivity(
                case_id=linked_case.id,
                actor_user_id=actor_id,
                activity_type="notification_acknowledged",
                payload_json={
                    "summary": f"{actor_label}已确认收到并处理该告警",
                    "actor_type": actor_role,
                    "notification_id": str(log.id),
                    "trace_id": log.trace_id,
                    "outbox_id": str(log.outbox_id) if log.outbox_id else None,
                },
                created_at=datetime.utcnow(),
            )
            db.add(acknowledgement_activity)

        if getattr(log, "acknowledged_at", None) is None:
            log.acknowledged_at = datetime.utcnow()
            log.acknowledged_by_user_id = actor_id
            log.acknowledgement_actor_role = actor_role
        await db.commit()
        await db.refresh(log)
        contexts = await _load_notification_contexts(db, [log])
        context = contexts.get(str(log.id), {})
        context["case"] = context.get("case") or linked_case
        context["ack_activity"] = context.get("ack_activity") or acknowledgement_activity
        item = _notification_item_json(log, user_id=elder_id, context=context)

    return {
        "status": "acknowledged",
        "item": item,
        "operator_case_id": str(linked_case.id) if linked_case is not None else None,
        "operator_case_status": linked_case.status if linked_case is not None else None,
    }


def _notification_ack_statement(notification_id: uuid.UUID, elder_id: uuid.UUID):
    """Serialize first acknowledgement so concurrent actors cannot duplicate audit events."""
    from app.db.models import NotificationLog

    return (
        select(NotificationLog)
        .where(
            NotificationLog.id == notification_id,
            NotificationLog.user_id == elder_id,
        )
        .with_for_update()
    )


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
    operator_id = _require_operator(user)
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
        households, decisions, outboxes = await _load_case_contexts(db, rows)
    return {
        "items": [
            _operator_case_json(
                row,
                actor_id=operator_id,
                household_id=households.get(row.user_id),
                decision=decisions.get(row.safety_decision_id),
                outbox=outboxes.get(row.notification_outbox_id),
            )
            for row in rows
        ],
        "total": len(rows),
    }


@router.get("/operator/cases/{case_id}")
async def get_operator_case(case_id: uuid.UUID, user: dict = Depends(get_current_user)):
    operator_id = _require_operator(user)
    from app.db.models import OperatorCase
    from app.db.session import async_session

    async with async_session() as db:
        row = await db.get(OperatorCase, case_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Operator case not found")
        households, decisions, outboxes = await _load_case_contexts(db, [row])
    return _operator_case_json(
        row,
        actor_id=operator_id,
        household_id=households.get(row.user_id),
        decision=decisions.get(row.safety_decision_id),
        outbox=outboxes.get(row.notification_outbox_id),
    )


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
        metadata = {
            key: value
            for key, value in body.metadata.items()
            if key not in RESERVED_ACTIVITY_METADATA
        }
        activity = CaseActivity(
            case_id=case_id,
            actor_user_id=operator_id,
            activity_type=body.activity_type,
            payload_json={**metadata, "summary": body.summary, "actor_type": "operator"},
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
        if body.status not in CASE_TRANSITIONS.get(row.status, set()):
            raise HTTPException(
                status_code=409,
                detail={"code": "invalid_case_transition", "from": row.status, "to": body.status},
            )
        if body.status in {"resolved", "closed"} and not (body.resolution or "").strip():
            raise HTTPException(
                status_code=422,
                detail={"code": "resolution_required", "status": body.status},
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
                payload_json={
                    "summary": f"Case transitioned from {previous} to {body.status}",
                    "actor_type": "operator",
                    "resolution": body.resolution,
                },
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
