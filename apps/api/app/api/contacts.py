from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.auth import get_current_user
from app.api.family_auth import get_managed_household
from app.api.households import _ensure_household
from app.config.settings import settings

router = APIRouter(prefix="/contacts", tags=["contacts"])


class ContactPointCreate(BaseModel):
    kind: Literal["phone", "sms", "email", "wechat", "webhook"]
    value: str = Field(min_length=3, max_length=512)
    label: str | None = Field(default=None, max_length=128)
    priority: int = Field(default=1, ge=1, le=100)
    availability: dict = Field(default_factory=dict)


class ContactPointUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=128)
    priority: int | None = Field(default=None, ge=1, le=100)
    availability: dict | None = None


class ChallengeVerify(BaseModel):
    code: str = Field(min_length=4, max_length=32)


class EmergencyContactCreate(BaseModel):
    contact_point_id: uuid.UUID
    name: str = Field(min_length=1, max_length=160)
    relation: str | None = Field(default=None, max_length=80)
    priority: int = Field(default=1, ge=1, le=100)
    notify_on_levels: list[str] = Field(default_factory=lambda: ["critical", "high"])
    webhook_url: str | None = None
    availability: dict = Field(default_factory=dict)


class RevokeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=512)


def _challenge_hash(code: str) -> str:
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def _deliver_challenge(row, challenge: str) -> None:
    if settings.app_env.lower() != "production":
        return
    from app.db.models import NotificationOutbox
    from app.db.session import async_session
    from app.workers.notification_outbox_worker import SUCCESS_STATES, resolve_provider

    async with async_session() as db:
        outbox = NotificationOutbox(
            user_id=row.user_id,
            provider=settings.notification_provider,
            channel=row.kind,
            idempotency_key=f"contact-verification:{row.id}:{int(row.challenge_expires_at.timestamp())}",
            payload_json={
                "event_type": "contact_verification",
                "contact_point_id": str(row.id),
                "channel": row.kind,
                "destination": row.value,
                "verification_code": challenge,
                "expires_at": row.challenge_expires_at.isoformat(),
            },
            state="sending",
        )
        db.add(outbox)
        await db.flush()
        result = await resolve_provider().send(outbox)
        outbox.payload_json = {
            "event_type": "contact_verification",
            "contact_point_id": str(row.id),
            "channel": row.kind,
            "destination": row.value,
            "challenge_digest": _challenge_hash(challenge),
            "expires_at": row.challenge_expires_at.isoformat(),
        }
        outbox.state = result.state
        outbox.provider_message_id = result.provider_message_id
        outbox.last_error = result.error
        outbox.attempt_count = 1
        outbox.updated_at = datetime.utcnow()
        contact = await db.get(type(row), row.id, with_for_update=True)
        if contact is None:
            raise HTTPException(status_code=404, detail="Contact point not found")
        contact.verification_outbox_id = outbox.id
        contact.updated_at = datetime.utcnow()
        await db.commit()
    row.verification_outbox_id = outbox.id
    if result.state not in SUCCESS_STATES:
        raise HTTPException(status_code=503, detail="Verification provider did not accept delivery")


async def _household_for_actor(user: dict, permission: str = "view_notifications"):
    managed = await get_managed_household(user, permission=permission)
    household_id = managed.household_id
    if household_id is None and managed.role == "elder":
        household_id = (await _ensure_household(managed.elder_id)).id
    if household_id is None:
        raise HTTPException(status_code=404, detail="Household not found")
    return managed, household_id


def _contact_point_json(row) -> dict:
    return {
        "id": str(row.id),
        "household_id": str(row.household_id),
        "user_id": str(row.user_id),
        "kind": row.kind,
        "channel": row.kind,
        "label": row.label,
        "name": row.label or row.value,
        "value": row.value,
        "priority": row.priority,
        "escalation_order": row.priority,
        "availability": row.availability_json or {},
        "verification_state": row.verification_state,
        "verification_status": (
            "pending" if row.verification_state == "challenge_pending" else row.verification_state
        ),
        "status": row.status,
        "available": row.status == "active" and row.revoked_at is None,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "last_verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }


@router.get("")
async def list_contact_points(user: dict = Depends(get_current_user)):
    _managed, household_id = await _household_for_actor(user)
    from app.db.models import ContactPoint
    from app.db.session import async_session

    async with async_session() as db:
        rows = (
            await db.execute(
                select(ContactPoint)
                .where(ContactPoint.household_id == household_id)
                .order_by(ContactPoint.priority.asc(), ContactPoint.created_at.asc())
            )
        ).scalars().all()
    return {"household_id": str(household_id), "items": [_contact_point_json(row) for row in rows]}


@router.post("")
async def create_contact_point(body: ContactPointCreate, user: dict = Depends(get_current_user)):
    managed, household_id = await _household_for_actor(user, permission="manage_reminders")
    from app.db.models import ContactPoint
    from app.db.session import async_session

    challenge = f"{secrets.randbelow(1000000):06d}"
    now = datetime.utcnow()
    row = ContactPoint(
        household_id=household_id,
        user_id=managed.elder_id,
        kind=body.kind,
        label=body.label,
        value=body.value,
        priority=body.priority,
        availability_json=body.availability,
        verification_state="challenge_pending",
        verification_challenge_hash=_challenge_hash(challenge),
        verification_attempt_count=0,
        verification_locked_at=None,
        challenge_expires_at=now + timedelta(minutes=15),
    )
    async with async_session() as db:
        db.add(row)
        try:
            await db.commit()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Contact point already exists") from exc
        await db.refresh(row)
        try:
            await _deliver_challenge(row, challenge)
        except HTTPException:
            row.verification_state = "delivery_failed"
            row.updated_at = datetime.utcnow()
            await db.commit()
            raise
    payload = _contact_point_json(row)
    if settings.app_env.lower() != "production":
        payload["challenge_code_dev"] = challenge
    return payload


@router.post("/{contact_point_id}/verification")
async def request_contact_point_verification(
    contact_point_id: uuid.UUID,
    user: dict = Depends(get_current_user),
):
    _managed, household_id = await _household_for_actor(user, permission="manage_reminders")
    from app.db.models import ContactPoint
    from app.db.session import async_session

    challenge = f"{secrets.randbelow(1000000):06d}"
    now = datetime.utcnow()
    async with async_session() as db:
        row = (
            await db.execute(
                select(ContactPoint).where(ContactPoint.id == contact_point_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None or row.household_id != household_id:
            raise HTTPException(status_code=404, detail="Contact point not found")
        if row.status != "active" or row.revoked_at is not None:
            raise HTTPException(status_code=409, detail="Contact point revoked")
        row.verification_state = "challenge_pending"
        row.verification_challenge_hash = _challenge_hash(challenge)
        row.verification_attempt_count = 0
        row.verification_locked_at = None
        row.challenge_expires_at = now + timedelta(minutes=15)
        row.updated_at = now
        await db.commit()
        await db.refresh(row)
        try:
            await _deliver_challenge(row, challenge)
        except HTTPException:
            row.verification_state = "delivery_failed"
            row.updated_at = datetime.utcnow()
            await db.commit()
            raise
    payload = _contact_point_json(row)
    if settings.app_env.lower() != "production":
        payload["challenge_code_dev"] = challenge
    return payload


@router.patch("/{contact_point_id}")
async def update_contact_point(
    contact_point_id: uuid.UUID,
    body: ContactPointUpdate,
    user: dict = Depends(get_current_user),
):
    _managed, household_id = await _household_for_actor(user, permission="manage_reminders")
    from app.db.models import ContactPoint
    from app.db.session import async_session

    async with async_session() as db:
        row = await db.get(ContactPoint, contact_point_id, with_for_update=True)
        if row is None or row.household_id != household_id:
            raise HTTPException(status_code=404, detail="Contact point not found")
        if body.label is not None:
            row.label = body.label
        if body.priority is not None:
            row.priority = body.priority
        if body.availability is not None:
            row.availability_json = body.availability
        row.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(row)
    return _contact_point_json(row)


@router.post("/{contact_point_id}/verify")
async def verify_contact_point(
    contact_point_id: uuid.UUID,
    body: ChallengeVerify,
    user: dict = Depends(get_current_user),
):
    _managed, household_id = await _household_for_actor(user, permission="manage_reminders")
    from app.db.models import ContactPoint, NotificationOutbox
    from app.db.session import async_session

    now = datetime.utcnow()
    async with async_session() as db:
        row = (
            await db.execute(
                select(ContactPoint).where(ContactPoint.id == contact_point_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None or row.household_id != household_id:
            raise HTTPException(status_code=404, detail="Contact point not found")
        if row.status != "active" or row.revoked_at is not None:
            raise HTTPException(status_code=409, detail="Contact point revoked")
        if row.verification_locked_at is not None or row.verification_attempt_count >= 5:
            raise HTTPException(status_code=423, detail="Verification challenge is locked")
        if row.challenge_expires_at is None or row.challenge_expires_at < now:
            row.verification_state = "challenge_expired"
            await db.commit()
            raise HTTPException(status_code=410, detail="Verification challenge expired")
        if settings.app_env.lower() == "production":
            outbox = await db.get(NotificationOutbox, row.verification_outbox_id)
            if outbox is None or outbox.state not in {"accepted", "delivered", "read"}:
                raise HTTPException(status_code=409, detail="Verification delivery is not provider-confirmed")
        if row.verification_challenge_hash != _challenge_hash(body.code):
            row.verification_attempt_count += 1
            if row.verification_attempt_count >= 5:
                row.verification_state = "challenge_locked"
                row.verification_locked_at = now
            row.updated_at = now
            await db.commit()
            raise HTTPException(status_code=403, detail="Invalid verification challenge")
        row.verification_state = "verified"
        row.verification_attempt_count = 0
        row.verification_challenge_hash = None
        row.verified_at = now
        row.updated_at = now
        await db.commit()
        await db.refresh(row)
    return _contact_point_json(row)


@router.post("/{contact_point_id}/revoke")
async def revoke_contact_point(
    contact_point_id: uuid.UUID,
    body: RevokeRequest,
    user: dict = Depends(get_current_user),
):
    _managed, household_id = await _household_for_actor(user, permission="manage_reminders")
    from app.db.models import ContactPoint, EmergencyContact
    from app.db.session import async_session

    now = datetime.utcnow()
    async with async_session() as db:
        row = await db.get(ContactPoint, contact_point_id)
        if row is None or row.household_id != household_id:
            raise HTTPException(status_code=404, detail="Contact point not found")
        row.status = "revoked"
        row.revoked_at = now
        row.revoke_reason = body.reason
        row.updated_at = now
        emergency_contacts = (
            await db.execute(
                select(EmergencyContact).where(EmergencyContact.contact_point_id == contact_point_id)
            )
        ).scalars().all()
        for contact in emergency_contacts:
            contact.is_active = False
            contact.revoked_at = now
            contact.revoke_reason = body.reason
            contact.updated_at = now
        await db.commit()
    return {"status": "revoked", "contact_point_id": str(contact_point_id)}


@router.delete("/{contact_point_id}")
async def delete_contact_point(
    contact_point_id: uuid.UUID,
    user: dict = Depends(get_current_user),
):
    result = await revoke_contact_point(contact_point_id, RevokeRequest(reason="deleted"), user)
    return {"deleted": result["status"] == "revoked", **result}


@router.post("/emergency")
async def create_emergency_contact(body: EmergencyContactCreate, user: dict = Depends(get_current_user)):
    managed, household_id = await _household_for_actor(user, permission="manage_reminders")
    from app.db.models import ContactPoint, EmergencyContact
    from app.db.session import async_session

    async with async_session() as db:
        point = await db.get(ContactPoint, body.contact_point_id)
        if point is None or point.household_id != household_id:
            raise HTTPException(status_code=404, detail="Contact point not found")
        if point.verification_state != "verified":
            raise HTTPException(status_code=409, detail="Contact point must be verified first")
        row = EmergencyContact(
            user_id=managed.elder_id,
            household_id=household_id,
            contact_point_id=point.id,
            name=body.name,
            phone=point.value if point.kind == "phone" else body.name,
            relation=body.relation,
            priority=body.priority,
            availability_json=body.availability,
            notify_on_levels=body.notify_on_levels,
            webhook_url=body.webhook_url if point.kind != "webhook" else point.value,
            verification_state="verified",
            verified_at=point.verified_at,
            is_active=True,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return {
        "id": str(row.id),
        "contact_point_id": str(row.contact_point_id),
        "name": row.name,
        "priority": row.priority,
        "verification_state": row.verification_state,
        "is_active": row.is_active,
    }


@router.get("/emergency")
async def list_emergency_contacts(user: dict = Depends(get_current_user)):
    _managed, household_id = await _household_for_actor(user)
    from app.db.models import EmergencyContact
    from app.db.session import async_session

    async with async_session() as db:
        rows = (
            await db.execute(
                select(EmergencyContact)
                .where(EmergencyContact.household_id == household_id)
                .order_by(EmergencyContact.priority.asc(), EmergencyContact.created_at.asc())
            )
        ).scalars().all()
    return {
        "household_id": str(household_id),
        "items": [
            {
                "id": str(row.id),
                "contact_point_id": str(row.contact_point_id) if row.contact_point_id else None,
                "name": row.name,
                "relation": row.relation,
                "priority": row.priority,
                "availability": row.availability_json or {},
                "notify_on_levels": row.notify_on_levels or [],
                "verification_state": row.verification_state,
                "is_active": row.is_active,
            }
            for row in rows
        ],
    }


@router.post("/emergency/{contact_id}/revoke")
async def revoke_emergency_contact(
    contact_id: uuid.UUID,
    body: RevokeRequest,
    user: dict = Depends(get_current_user),
):
    _managed, household_id = await _household_for_actor(user, permission="manage_reminders")
    from app.db.models import EmergencyContact
    from app.db.session import async_session

    now = datetime.utcnow()
    async with async_session() as db:
        row = await db.get(EmergencyContact, contact_id)
        if row is None or row.household_id != household_id:
            raise HTTPException(status_code=404, detail="Emergency contact not found")
        row.is_active = False
        row.revoked_at = now
        row.revoke_reason = body.reason
        row.updated_at = now
        await db.commit()
    return {"status": "revoked", "emergency_contact_id": str(contact_id)}
