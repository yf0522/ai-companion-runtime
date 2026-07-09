"""Notification outbox worker and provider adapters."""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select, update

from app.config.settings import settings
from app.workers.celery_app import app

ProviderState = Literal["accepted", "delivered", "read", "failed", "expired", "unknown", "unconfigured"]
LEASE_SECONDS = 300
RETRYABLE_STATES = {"queued", "retry_scheduled", "sending"}
SUCCESS_STATES = {"accepted", "delivered", "read"}
TERMINAL_FAILURE_STATES = {"failed", "expired", "dead_letter", "unconfigured"}
STATE_RANK = {
    "queued": 0,
    "retry_scheduled": 0,
    "sending": 0,
    "unknown": 1,
    "accepted": 2,
    "delivered": 3,
    "read": 4,
    "failed": 5,
    "expired": 5,
    "dead_letter": 5,
    "unconfigured": 5,
}


@dataclass(frozen=True)
class ProviderResult:
    state: ProviderState
    provider_message_id: str | None = None
    error: str | None = None
    permanent: bool = False


@dataclass(frozen=True)
class ClaimedOutbox:
    id: uuid.UUID
    provider: str
    idempotency_key: str
    payload_json: dict[str, Any]
    attempt_count: int
    attempt_identity: str
    lease_owner: str


class SandboxNotificationProvider:
    """Deterministic local provider for tests and development evidence."""

    async def send(self, outbox: Any) -> ProviderResult:
        payload = outbox.payload_json or {}
        summary = str(payload.get("summary") or "")
        seed = f"{outbox.idempotency_key}:{summary}".encode("utf-8")
        message_id = "sandbox_" + hashlib.sha256(seed).hexdigest()[:20]
        if "permanent_fail" in summary:
            return ProviderResult("failed", message_id, "sandbox permanent failure", permanent=True)
        if "expire" in summary:
            return ProviderResult("expired", message_id, "sandbox expired")
        if "unknown" in summary or "timeout" in summary:
            return ProviderResult("unknown", message_id, "sandbox unknown provider state")
        return ProviderResult("accepted", message_id)


class UnconfiguredNotificationProvider:
    async def send(self, outbox: Any) -> ProviderResult:
        return ProviderResult(
            "unconfigured",
            None,
            "No production notification provider is configured",
            permanent=True,
        )


def resolve_provider(provider_name: str | None = None):
    name = (provider_name or settings.notification_provider or "unconfigured").lower()
    if settings.app_env.lower() == "production" and name == "sandbox":
        return UnconfiguredNotificationProvider()
    if name == "sandbox":
        return SandboxNotificationProvider()
    return UnconfiguredNotificationProvider()


def _receipt_identity(
    *,
    outbox_id: uuid.UUID,
    event_type: ProviderState,
    provider_message_id: str | None,
) -> str:
    if provider_message_id:
        return f"{event_type}:{provider_message_id}"
    return f"{event_type}:outbox:{outbox_id}"


def _should_apply_receipt_state(current_state: str | None, event_type: ProviderState) -> bool:
    current = current_state or "queued"
    if current in TERMINAL_FAILURE_STATES:
        return event_type in TERMINAL_FAILURE_STATES and event_type == current
    return STATE_RANK.get(event_type, 0) >= STATE_RANK.get(current, 0)


def _provider_result_update_values(
    *,
    result: ProviderResult,
    attempt_count: int,
    now: datetime,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "last_error": result.error,
        "lease_owner": None,
        "lease_until": None,
        "updated_at": now,
    }
    if result.provider_message_id is not None:
        values["provider_message_id"] = result.provider_message_id
    if result.state in SUCCESS_STATES:
        values["state"] = result.state
        values["next_attempt_at"] = None
    elif result.permanent or attempt_count >= 3:
        values["state"] = "dead_letter" if result.state == "unconfigured" else result.state
        values["next_attempt_at"] = None
    else:
        values["state"] = "retry_scheduled"
        values["next_attempt_at"] = now + timedelta(minutes=2 * attempt_count)
    return values


async def _insert_receipt_once(
    db: Any,
    *,
    outbox_id: uuid.UUID,
    event_type: ProviderState,
    provider_message_id: str | None,
    payload: dict[str, Any],
    occurred_at: datetime,
) -> None:
    from app.db.models import NotificationReceipt

    identity = _receipt_identity(
        outbox_id=outbox_id,
        event_type=event_type,
        provider_message_id=provider_message_id,
    )
    existing = (
        await db.execute(
            select(NotificationReceipt).where(
                NotificationReceipt.outbox_id == outbox_id,
                NotificationReceipt.receipt_identity == identity,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            NotificationReceipt(
                outbox_id=outbox_id,
                provider_message_id=provider_message_id,
                receipt_identity=identity,
                event_type=event_type,
                payload_json=payload,
                occurred_at=occurred_at,
            )
        )


async def _claim_due_outbox(
    *,
    limit: int,
    now: datetime,
    lease_owner: str,
) -> list[ClaimedOutbox]:
    from app.db.models import NotificationOutbox
    from app.db.session import async_session

    lease_until = now + timedelta(seconds=LEASE_SECONDS)
    async with async_session() as db:
        stmt = (
            select(NotificationOutbox)
            .where(
                NotificationOutbox.state.in_(list(RETRYABLE_STATES)),
                (NotificationOutbox.next_attempt_at.is_(None) | (NotificationOutbox.next_attempt_at <= now)),
                (NotificationOutbox.lease_until.is_(None) | (NotificationOutbox.lease_until <= now)),
            )
            .order_by(NotificationOutbox.created_at.asc())
            .limit(limit)
        )
        stmt = stmt.with_for_update(skip_locked=True)
        outboxes = (await db.execute(stmt)).scalars().all()
        claimed: list[ClaimedOutbox] = []
        for outbox in outboxes:
            attempt_count = (outbox.attempt_count or 0) + 1
            attempt_identity = str(uuid.uuid4())
            outbox.state = "sending"
            outbox.lease_owner = lease_owner
            outbox.lease_until = lease_until
            outbox.attempt_identity = attempt_identity
            outbox.attempt_count = attempt_count
            outbox.updated_at = now
            claimed.append(
                ClaimedOutbox(
                    id=outbox.id,
                    provider=outbox.provider,
                    idempotency_key=outbox.idempotency_key,
                    payload_json=dict(outbox.payload_json or {}),
                    attempt_count=attempt_count,
                    attempt_identity=attempt_identity,
                    lease_owner=lease_owner,
                )
            )
        await db.commit()
        return claimed


async def _finish_claimed_outbox(
    claimed: ClaimedOutbox,
    result: ProviderResult,
    *,
    now: datetime,
) -> bool:
    from app.db.models import NotificationOutbox
    from app.db.session import async_session

    values = _provider_result_update_values(
        result=result,
        attempt_count=claimed.attempt_count,
        now=now,
    )

    async with async_session() as db:
        write = await db.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.id == claimed.id,
                NotificationOutbox.state == "sending",
                NotificationOutbox.lease_owner == claimed.lease_owner,
                NotificationOutbox.attempt_identity == claimed.attempt_identity,
            )
            .values(**values)
        )
        if write.rowcount != 1:
            await db.rollback()
            return False
        await _insert_receipt_once(
            db,
            outbox_id=claimed.id,
            provider_message_id=result.provider_message_id,
            event_type=result.state,
            payload={"error": result.error, "permanent": result.permanent},
            occurred_at=now,
        )
        await db.commit()
        return True


async def create_safety_notification_pipeline(
    *,
    user_id: str,
    risk_level: str,
    risk_category: str,
    summary: str,
    trace_id: str | None = None,
    policy_version: str = "risk-rules:v1",
    action: str = "notify_family",
    evidence_ref: str | None = None,
    evidence_json: dict[str, Any] | None = None,
    confidence: float | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Commit safety decision, notification outbox/log, and case in one DB transaction."""
    from app.db.models import (
        EmergencyContact,
        NotificationLog,
        NotificationOutbox,
        OperatorCase,
        SafetyDecision,
    )
    from app.db.session import async_session

    db_user_id = uuid.UUID(user_id)
    now = datetime.utcnow()
    provider_name = provider or settings.notification_provider
    async with async_session() as db:
        decision = SafetyDecision(
            user_id=db_user_id,
            trace_id=trace_id,
            policy_version=policy_version,
            risk_level=risk_level,
            risk_category=risk_category,
            action=action,
            evidence_ref=evidence_ref,
            evidence_json=evidence_json or {},
            confidence=confidence,
            calibration="rule",
        )
        db.add(decision)
        await db.flush()

        contacts = (
            await db.execute(
                select(EmergencyContact)
                .where(
                    EmergencyContact.user_id == db_user_id,
                    EmergencyContact.is_active.is_(True),
                )
                .order_by(EmergencyContact.priority)
            )
        ).scalars().all()
        matched_contacts = [
            contact
            for contact in contacts
            if risk_level in (contact.notify_on_levels or ["critical", "high"])
        ]

        outbox_ids: list[str] = []
        if not matched_contacts:
            log = NotificationLog(
                user_id=db_user_id,
                contact_id=None,
                trace_id=trace_id,
                risk_level=risk_level,
                risk_category=risk_category,
                summary=summary,
                webhook_status="no_contact",
                safety_decision_id=decision.id,
            )
            db.add(log)
            case = OperatorCase(
                user_id=db_user_id,
                safety_decision_id=decision.id,
                status="open",
                severity=risk_level,
                summary=summary,
                due_at=now + timedelta(minutes=30),
            )
            db.add(case)
            await db.commit()
            return {
                "status": "persisted",
                "safety_decision_id": str(decision.id),
                "outbox_ids": [],
                "case_opened": True,
                "webhook_status": "no_contact",
            }

        for contact in matched_contacts:
            idempotency_key = f"safety:{decision.id}:contact:{contact.id}"
            outbox = NotificationOutbox(
                user_id=db_user_id,
                safety_decision_id=decision.id,
                contact_id=contact.id,
                provider=provider_name,
                channel="webhook" if contact.webhook_url else "sandbox",
                idempotency_key=idempotency_key,
                payload_json={
                    "user_id": str(db_user_id),
                    "risk_level": risk_level,
                    "risk_category": risk_category,
                    "summary": summary,
                    "trace_id": trace_id,
                    "contact_id": str(contact.id),
                    "contact_name": contact.name,
                },
                state="queued",
                next_attempt_at=now,
            )
            db.add(outbox)
            await db.flush()
            db.add(
                NotificationLog(
                    user_id=db_user_id,
                    contact_id=contact.id,
                    trace_id=trace_id,
                    risk_level=risk_level,
                    risk_category=risk_category,
                    summary=summary,
                    webhook_status="queued",
                    safety_decision_id=decision.id,
                    outbox_id=outbox.id,
                )
            )
            case = OperatorCase(
                user_id=db_user_id,
                safety_decision_id=decision.id,
                notification_outbox_id=outbox.id,
                status="open",
                severity=risk_level,
                summary=summary,
                due_at=now + timedelta(minutes=30),
            )
            db.add(case)
            outbox_ids.append(str(outbox.id))

        await db.commit()
        return {
            "status": "persisted",
            "safety_decision_id": str(decision.id),
            "outbox_ids": outbox_ids,
            "case_opened": True,
            "webhook_status": "queued",
        }


@app.task(name="app.workers.notification_outbox_worker.deliver_notification_outbox")
def deliver_notification_outbox() -> dict[str, int]:
    return asyncio.run(deliver_due_outbox())


async def deliver_due_outbox(limit: int = 50) -> dict[str, int]:
    now = datetime.utcnow()
    lease_owner = f"notification-outbox:{uuid.uuid4()}"
    claimed_outboxes = await _claim_due_outbox(limit=limit, now=now, lease_owner=lease_owner)
    delivered = 0
    failed = 0
    stale = 0
    for outbox in claimed_outboxes:
        result = await resolve_provider(outbox.provider).send(outbox)
        applied = await _finish_claimed_outbox(outbox, result, now=datetime.utcnow())
        if not applied:
            stale += 1
            continue
        if result.state in SUCCESS_STATES:
            delivered += 1
        elif result.permanent or outbox.attempt_count >= 3:
            failed += 1
    return {
        "processed": len(claimed_outboxes) - stale,
        "claimed": len(claimed_outboxes),
        "delivered": delivered,
        "failed": failed,
        "stale": stale,
    }


async def record_provider_receipt(
    *,
    outbox_id: str,
    event_type: ProviderState,
    provider_message_id: str | None = None,
    payload: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    expected_user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    from app.db.models import NotificationOutbox
    from app.db.session import async_session

    oid = uuid.UUID(outbox_id)
    occurred = occurred_at or datetime.utcnow()
    async with async_session() as db:
        stmt = select(NotificationOutbox).where(NotificationOutbox.id == oid)
        if expected_user_id is not None:
            stmt = stmt.where(NotificationOutbox.user_id == expected_user_id)
        outbox = (await db.execute(stmt)).scalar_one_or_none()
        if outbox is None:
            raise LookupError("notification_outbox_not_found")
        await _insert_receipt_once(
            db,
            outbox_id=oid,
            provider_message_id=provider_message_id,
            event_type=event_type,
            payload=payload or {},
            occurred_at=occurred,
        )
        if _should_apply_receipt_state(outbox.state, event_type):
            outbox.provider_message_id = provider_message_id or outbox.provider_message_id
            outbox.state = event_type
            outbox.updated_at = datetime.utcnow()
        await db.commit()
        return {"outbox_id": str(outbox.id), "state": outbox.state}
