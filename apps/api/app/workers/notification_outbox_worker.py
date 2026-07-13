"""Notification outbox worker and provider adapters."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.config.settings import settings
from app.workers.async_runner import run_async_task
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


class SignedWebhookNotificationProvider:
    """Production generic webhook provider with HMAC-signed outbound delivery."""

    async def send(self, outbox: Any) -> ProviderResult:
        if not settings.notification_outbound_url or not settings.notification_webhook_secret:
            return ProviderResult(
                "unconfigured",
                None,
                "Signed webhook provider requires outbound URL and HMAC secret",
                permanent=True,
            )
        timestamp = str(int(datetime.utcnow().timestamp()))
        payload = dict(outbox.payload_json or {})
        payload.setdefault("outbox_id", str(outbox.id))
        payload.setdefault("event_type", "accepted")
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        signature = _webhook_signature(timestamp, body.encode("utf-8"))
        event_id = str(outbox.id)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    settings.notification_outbound_url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Companion-Timestamp": timestamp,
                        "X-Companion-Signature": signature,
                        "X-Companion-Event-Id": event_id,
                        "Idempotency-Key": outbox.idempotency_key,
                    },
                )
            if 200 <= response.status_code < 300:
                provider_message_id = response.headers.get("X-Provider-Message-Id") or event_id
                return ProviderResult("accepted", provider_message_id)
            permanent = 400 <= response.status_code < 500 and response.status_code not in {408, 409, 429}
            return ProviderResult(
                "failed" if permanent else "unknown",
                event_id,
                f"signed webhook returned HTTP {response.status_code}",
                permanent=permanent,
            )
        except httpx.HTTPError as exc:
            return ProviderResult("unknown", event_id, str(exc), permanent=False)


def resolve_provider(provider_name: str | None = None):
    name = (provider_name or settings.notification_provider or "unconfigured").lower()
    if settings.app_env.lower() == "production" and name == "sandbox":
        return UnconfiguredNotificationProvider()
    if name == "signed_webhook":
        return SignedWebhookNotificationProvider()
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


def _webhook_signature(timestamp: str, raw_body: bytes) -> str:
    digest = hmac.new(
        settings.notification_webhook_secret.encode("utf-8"),
        timestamp.encode("utf-8") + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _verify_webhook_signature(timestamp: str | None, signature: str | None, raw_body: bytes) -> datetime:
    if not settings.notification_webhook_secret.strip():
        raise PermissionError("Webhook signing secret is not configured")
    if not timestamp or not signature:
        raise PermissionError("Missing webhook signature")
    try:
        ts = datetime.utcfromtimestamp(int(timestamp))
    except (TypeError, ValueError) as exc:
        raise PermissionError("Invalid webhook timestamp") from exc
    age = abs((datetime.utcnow() - ts).total_seconds())
    if age > settings.notification_webhook_tolerance_seconds:
        raise PermissionError("Webhook timestamp outside tolerance")
    expected = _webhook_signature(timestamp, raw_body)
    if not hmac.compare_digest(expected, signature):
        raise PermissionError("Invalid webhook signature")
    return ts


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


async def _record_reconciliation(
    db: Any,
    *,
    outbox_id: uuid.UUID,
    provider: str,
    reason: str,
    observed_state: str | None,
    payload: dict[str, Any] | None = None,
) -> None:
    from app.db.models import NotificationReconciliation

    existing = (
        await db.execute(
            select(NotificationReconciliation).where(
                NotificationReconciliation.outbox_id == outbox_id,
                NotificationReconciliation.reason == reason,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    db.add(
        NotificationReconciliation(
            outbox_id=outbox_id,
            provider=provider,
            state="pending",
            reason=reason,
            observed_state=observed_state,
            payload_json=payload or {},
        )
    )


async def _claim_family_contact_request(
    *,
    user_id: uuid.UUID,
    trace_id: str,
    summary: str,
) -> tuple[str, uuid.UUID | None, dict[str, Any] | None]:
    """Claim one explicit contact request per trace before creating side effects."""
    from app.db.models import IdempotencyRecord
    from app.db.session import async_session

    operation = "contact:request"
    request_hash = hashlib.sha256(
        json.dumps(
            {"user_id": str(user_id), "trace_id": trace_id, "summary": summary},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    async with async_session() as db:
        record = IdempotencyRecord(
            user_id=user_id,
            key=trace_id,
            operation=operation,
            resource_type="family_contact_request",
            request_hash=request_hash,
            response_json={},
            error_json={},
            status="in_progress",
            status_code=202,
        )
        db.add(record)
        try:
            await db.commit()
            return "won", record.id, None
        except IntegrityError:
            await db.rollback()
            existing = (
                await db.execute(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.user_id == user_id,
                        IdempotencyRecord.key == trace_id,
                        IdempotencyRecord.operation == operation,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                return "failed", None, {"reason": "idempotency_recovery_failed"}
            if existing.request_hash != request_hash:
                return "failed", existing.id, {"reason": "idempotency_payload_mismatch"}
            if existing.status == "completed":
                replay = dict(existing.response_json or {})
                replay["idempotent_replay"] = True
                return "replay", existing.id, replay
            if existing.status == "failed":
                return "failed", existing.id, dict(existing.error_json or {})
            return "in_progress", existing.id, {
                "status": "in_progress",
                "request_id": str(existing.resource_id) if existing.resource_id else None,
                "outbox_ids": [],
                "case_opened": False,
                "delivery_status": "pending",
            }


async def _finish_family_contact_request(
    *,
    record_id: uuid.UUID | None,
    resource_id: uuid.UUID | None,
    response: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    if record_id is None:
        return
    from app.db.models import IdempotencyRecord
    from app.db.session import async_session

    async with async_session() as db:
        record = await db.get(IdempotencyRecord, record_id)
        if record is None:
            return
        if record.status != "in_progress":
            return
        record.resource_id = resource_id
        record.status = "completed" if response is not None else "failed"
        record.response_json = response or {}
        record.error_json = error or {}
        record.status_code = 200 if response is not None else 500
        record.updated_at = datetime.utcnow()
        await db.commit()


async def create_family_contact_request_pipeline(
    *,
    user_id: str,
    summary: str,
    trace_id: str,
    provider: str | None = None,
) -> dict[str, Any]:
    """Persist an explicit elder request to contact family without claiming delivery."""
    from app.db.models import (
        EmergencyContact,
        IdempotencyRecord,
        NotificationLog,
        NotificationOutbox,
        OperatorCase,
        SafetyDecision,
    )
    from app.db.session import async_session

    db_user_id = uuid.UUID(user_id)
    claim_state, claim_id, claim_payload = await _claim_family_contact_request(
        user_id=db_user_id,
        trace_id=trace_id,
        summary=summary,
    )
    if claim_state in {"replay", "in_progress"}:
        return claim_payload or {
            "status": "in_progress",
            "outbox_ids": [],
            "case_opened": False,
            "delivery_status": "pending",
        }
    if claim_state == "failed":
        return {
            "status": "failed",
            "outbox_ids": [],
            "case_opened": False,
            "delivery_status": "failed",
            **(claim_payload or {}),
        }

    now = datetime.utcnow()
    provider_name = provider or settings.notification_provider
    decision_id: uuid.UUID | None = None
    try:
        async with async_session() as db:
            decision = SafetyDecision(
                user_id=db_user_id,
                trace_id=trace_id,
                policy_version="family-contact-request:v1",
                risk_level="medium",
                risk_category="family_contact_request",
                action="notify_family_user_requested",
                evidence_ref=f"trace:{trace_id}",
                evidence_json={"explicit_user_request": True, "source": "elder_chat"},
                confidence=1.0,
                calibration="explicit_user_request",
            )
            db.add(decision)
            await db.flush()
            decision_id = decision.id

            contacts = (
                await db.execute(
                    select(EmergencyContact)
                    .where(
                        EmergencyContact.user_id == db_user_id,
                        EmergencyContact.is_active.is_(True),
                        EmergencyContact.verification_state == "verified",
                        EmergencyContact.revoked_at.is_(None),
                    )
                    .order_by(EmergencyContact.priority)
                )
            ).scalars().all()

            outbox_ids: list[str] = []
            if not contacts:
                db.add(
                    NotificationLog(
                        user_id=db_user_id,
                        contact_id=None,
                        trace_id=trace_id,
                        risk_level="medium",
                        risk_category="family_contact_request",
                        summary=summary,
                        webhook_status="no_contact",
                        safety_decision_id=decision.id,
                    )
                )
                db.add(
                    OperatorCase(
                        user_id=db_user_id,
                        safety_decision_id=decision.id,
                        status="unstaffed",
                        severity="medium",
                        summary=summary,
                        due_at=now + timedelta(minutes=30),
                        sla_deadline_at=now + timedelta(minutes=30),
                    )
                )
                response = {
                    "status": "persisted",
                    "request_id": str(decision.id),
                    "outbox_ids": [],
                    "case_opened": True,
                    "delivery_status": "no_verified_contact",
                }
            else:
                for contact in contacts:
                    outbox = NotificationOutbox(
                        user_id=db_user_id,
                        safety_decision_id=decision.id,
                        contact_id=contact.id,
                        provider=provider_name,
                        channel="webhook" if contact.webhook_url else "provider",
                        idempotency_key=f"contact-request:{trace_id}:contact:{contact.id}",
                        payload_json={
                            "event_type": "family_contact_request",
                            "user_id": str(db_user_id),
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
                            risk_level="medium",
                            risk_category="family_contact_request",
                            summary=summary,
                            webhook_status="queued",
                            safety_decision_id=decision.id,
                            outbox_id=outbox.id,
                        )
                    )
                    db.add(
                        OperatorCase(
                            user_id=db_user_id,
                            safety_decision_id=decision.id,
                            notification_outbox_id=outbox.id,
                            status="unstaffed",
                            severity="medium",
                            summary=summary,
                            due_at=now + timedelta(minutes=30),
                            sla_deadline_at=now + timedelta(minutes=30),
                        )
                    )
                    outbox_ids.append(str(outbox.id))
                response = {
                    "status": "persisted",
                    "request_id": str(decision.id),
                    "outbox_ids": outbox_ids,
                    "case_opened": True,
                    "delivery_status": "queued",
                }
            if claim_id is None:
                raise RuntimeError("contact_request_missing_idempotency_claim")
            claim_record = await db.get(IdempotencyRecord, claim_id)
            if claim_record is None or claim_record.status != "in_progress":
                raise RuntimeError("contact_request_idempotency_claim_unavailable")
            claim_record.resource_id = decision.id
            claim_record.status = "completed"
            claim_record.response_json = response
            claim_record.error_json = {}
            claim_record.status_code = 200
            claim_record.updated_at = now
            # The user-visible request, outbox/case, and replay response become
            # durable in one commit. There is no successful side effect with a
            # permanently in-progress idempotency record.
            await db.commit()
        return response
    except Exception as exc:
        await _finish_family_contact_request(
            record_id=claim_id,
            resource_id=decision_id,
            error={"reason": "contact_request_persistence_failed", "error": str(exc)},
        )
        raise


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
                    EmergencyContact.verification_state == "verified",
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
                status="unstaffed",
                severity=risk_level,
                summary=summary,
                due_at=now + timedelta(minutes=30),
                sla_deadline_at=now + timedelta(minutes=30),
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
                channel="webhook" if contact.webhook_url else "provider",
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
                status="unstaffed",
                severity=risk_level,
                summary=summary,
                due_at=now + timedelta(minutes=30),
                sla_deadline_at=now + timedelta(minutes=30),
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


async def persist_nonblocking_safety_decision(
    *,
    user_id: str,
    risk_level: str,
    risk_category: str,
    trace_id: str | None,
    evidence_json: dict[str, Any] | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Persist a non-blocking safety decision without notification side effects."""
    from app.db.models import SafetyDecision
    from app.db.session import async_session

    async with async_session() as db:
        decision = SafetyDecision(
            user_id=uuid.UUID(user_id),
            trace_id=trace_id,
            policy_version="risk-rules:v1",
            risk_level=risk_level,
            risk_category=risk_category,
            action="record_and_companion",
            evidence_ref=f"trace:{trace_id}" if trace_id else None,
            evidence_json=evidence_json or {},
            confidence=confidence,
            calibration="rule",
        )
        db.add(decision)
        await db.flush()
        await db.commit()
        return {
            "status": "persisted",
            "safety_decision_id": str(decision.id),
            "outbox_ids": [],
            "case_opened": False,
            "webhook_status": "not_requested",
        }


@app.task(name="app.workers.notification_outbox_worker.deliver_notification_outbox")
def deliver_notification_outbox() -> dict[str, int]:
    return run_async_task(deliver_due_outbox)


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
            if event_type in SUCCESS_STATES:
                outbox.reconciliation_state = "not_required"
        await db.commit()
        return {"outbox_id": str(outbox.id), "state": outbox.state}


async def record_signed_provider_receipt(
    *,
    body: dict[str, Any],
    raw_body: bytes,
    timestamp_header: str | None,
    signature_header: str | None,
    event_id: str | None,
) -> dict[str, Any]:
    signature_ts = _verify_webhook_signature(timestamp_header, signature_header, raw_body)
    outbox_id = str(body.get("outbox_id") or event_id or "")
    event_type = body.get("event_type")
    if event_type not in SUCCESS_STATES | TERMINAL_FAILURE_STATES | {"unknown"}:
        raise ValueError("Unsupported receipt event_type")
    receipt_identity = event_id or str(body.get("receipt_identity") or "")
    if not receipt_identity:
        raise ValueError("Receipt event id required")

    from app.db.models import NotificationOutbox, NotificationReceipt
    from app.db.session import async_session

    oid = uuid.UUID(outbox_id)
    async with async_session() as db:
        outbox = (await db.execute(select(NotificationOutbox).where(NotificationOutbox.id == oid))).scalar_one_or_none()
        if outbox is None:
            raise LookupError("notification_outbox_not_found")
        existing = (
            await db.execute(
                select(NotificationReceipt).where(
                    NotificationReceipt.outbox_id == oid,
                    NotificationReceipt.receipt_identity == receipt_identity,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise FileExistsError("Receipt replay detected")
        db.add(
            NotificationReceipt(
                outbox_id=oid,
                provider_message_id=body.get("provider_message_id"),
                receipt_identity=receipt_identity,
                signature_timestamp=signature_ts,
                event_type=event_type,
                payload_json=body,
                occurred_at=datetime.utcnow(),
            )
        )
        if _should_apply_receipt_state(outbox.state, event_type):
            outbox.provider_message_id = body.get("provider_message_id") or outbox.provider_message_id
            outbox.state = event_type
            outbox.updated_at = datetime.utcnow()
            if event_type in SUCCESS_STATES:
                outbox.reconciliation_state = "not_required"
        await db.commit()
        return {"outbox_id": str(outbox.id), "state": outbox.state}


@app.task(name="app.workers.notification_outbox_worker.reconcile_notification_outbox")
def reconcile_notification_outbox() -> dict[str, int]:
    return run_async_task(reconcile_stale_outbox)


async def reconcile_stale_outbox(limit: int = 100) -> dict[str, int]:
    from app.db.models import NotificationOutbox
    from app.db.session import async_session

    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=10)
    async with async_session() as db:
        rows = (
            await db.execute(
                select(NotificationOutbox)
                .where(
                    NotificationOutbox.provider == "signed_webhook",
                    NotificationOutbox.state.in_(["accepted", "unknown", "sending"]),
                    NotificationOutbox.updated_at <= cutoff,
                )
                .order_by(NotificationOutbox.updated_at.asc())
                .limit(limit)
            )
        ).scalars().all()
        for row in rows:
            row.reconciliation_state = "pending"
            row.updated_at = now
            await _record_reconciliation(
                db,
                outbox_id=row.id,
                provider=row.provider,
                reason="receipt_timeout",
                observed_state=row.state,
                payload={"updated_at": row.updated_at.isoformat() if row.updated_at else None},
            )
        await db.commit()
    return {"reconciled": len(rows)}
