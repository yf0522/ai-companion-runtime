from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.auth import get_current_user
from app.api.family_auth import get_managed_household
from app.api.households import InviteCreate, _consume_invite, _ensure_household, create_invite, revoke_binding

router = APIRouter(prefix="/care-circle", tags=["care-circle"])


class CareCircleInviteCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = "caregiver"
    permissions: list[str] = Field(default_factory=list)


class BindingUpdate(BaseModel):
    permissions: list[str]


class ConsentUpdate(BaseModel):
    approved: bool


@router.get("")
async def list_care_circle(user: dict = Depends(get_current_user)):
    managed = await get_managed_household(user, permission="view_notifications")
    household_id = managed.household_id
    if household_id is None and managed.role == "elder":
        household_id = (await _ensure_household(managed.elder_id)).id
    if household_id is None:
        raise HTTPException(status_code=404, detail="Household not found")

    from app.db.models import CareCircleMember, FamilyBinding, HouseholdInvite, User
    from app.db.session import async_session

    async with async_session() as db:
        members = (
            await db.execute(
                select(CareCircleMember)
                .where(CareCircleMember.household_id == household_id)
                .order_by(CareCircleMember.created_at.asc())
            )
        ).scalars().all()
        bindings = (
            await db.execute(
                select(FamilyBinding).where(
                    FamilyBinding.household_id == household_id,
                    FamilyBinding.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        users = {
            row.id: row
            for row in (
                await db.execute(select(User).where(User.id.in_([member.user_id for member in members])))
            ).scalars().all()
        }
        invites = (
            await db.execute(
                select(HouseholdInvite)
                .where(HouseholdInvite.household_id == household_id)
                .order_by(HouseholdInvite.created_at.desc())
                .limit(50)
            )
        ).scalars().all()
    binding_by_user = {binding.family_user_id: binding for binding in bindings}
    return {
        "household_id": str(household_id),
        "members": [
            {
                "id": str(member.id),
                "name": users.get(member.user_id).username if users.get(member.user_id) else "Unknown member",
                "user_id": str(member.user_id),
                "binding_id": (
                    str(binding_by_user[member.user_id].id)
                    if member.user_id in binding_by_user
                    else None
                ),
                "role": member.role,
                "status": member.status,
                "consent_status": (
                    binding_by_user[member.user_id].consent_status
                    if member.user_id in binding_by_user
                    else "owner"
                ),
                "permissions": member.permissions or [],
            }
            for member in members
        ],
        "active_bindings": [
            {
                "id": str(binding.id),
                "family_user_id": str(binding.family_user_id),
                "elder_user_id": str(binding.elder_user_id),
                "permissions": binding.permissions or [],
                "version": binding.version,
            }
            for binding in bindings
        ],
        "permissions": [],
        "invites": [
            {
                "email": invite.invitee_email,
                "role": "caregiver",
                "status": invite.status,
                "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
            }
            for invite in invites
        ],
    }


@router.post("/invites")
async def invite_care_circle_member(
    body: CareCircleInviteCreate,
    user: dict = Depends(get_current_user),
):
    managed = await get_managed_household(user, permission="view_notifications")
    if managed.role != "elder":
        raise HTTPException(status_code=403, detail="Only the elder can invite care-circle members")
    household = await _ensure_household(managed.elder_id)
    permissions = body.permissions or ["view_reminders", "view_notifications"]
    if "view_notifications" not in permissions and any(
        permission in permissions for permission in {"view_alerts", "view_summary"}
    ):
        permissions = [*permissions, "view_notifications"]
    result = await create_invite(
        household.id,
        InviteCreate(invitee_email=body.email, permissions=permissions),
        user,
    )
    return {**result, "email": body.email, "role": body.role}


@router.post("/invites/{token}/accept")
async def accept_care_circle_invite(
    token: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: dict = Depends(get_current_user),
):
    if user.get("role") != "family":
        raise HTTPException(status_code=403, detail="Family account required to accept invite")
    nonce = idempotency_key or secrets.token_urlsafe(16)
    return await _consume_invite(token, uuid.UUID(user["sub"]), nonce, "accepted")


@router.post("/invites/{token}/deny")
async def deny_care_circle_invite(
    token: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: dict = Depends(get_current_user),
):
    nonce = idempotency_key or secrets.token_urlsafe(16)
    return await _consume_invite(token, uuid.UUID(user["sub"]), nonce, "denied")


@router.patch("/bindings/{binding_id}")
async def update_care_circle_binding(
    binding_id: uuid.UUID,
    body: BindingUpdate,
    user: dict = Depends(get_current_user),
):
    managed = await get_managed_household(user, permission="view_notifications")
    if managed.role != "elder":
        raise HTTPException(status_code=403, detail="Only the elder can change care-circle permissions")
    from app.db.models import BindingAuditEvent, FamilyBinding
    from app.db.session import async_session

    async with async_session() as db:
        binding = await db.get(FamilyBinding, binding_id)
        if binding is None or binding.elder_user_id != managed.elder_id:
            raise HTTPException(status_code=404, detail="Binding not found")
        binding.permissions = body.permissions
        binding.version = (binding.version or 1) + 1
        db.add(
            BindingAuditEvent(
                binding_id=binding.id,
                household_id=binding.household_id,
                actor_user_id=managed.actor_id,
                event_type="binding.permissions_updated",
                payload_json={"permissions": body.permissions, "version": binding.version},
            )
        )
        await db.commit()
    return {
        "id": str(binding.id),
        "binding_id": str(binding.id),
        "role": "caregiver",
        "status": binding.status,
        "permissions": binding.permissions or [],
        "escalation_order": None,
    }


@router.post("/bindings/{binding_id}/consent")
async def update_care_circle_consent(
    binding_id: uuid.UUID,
    body: ConsentUpdate,
    user: dict = Depends(get_current_user),
):
    if user.get("role", "elder") != "elder":
        raise HTTPException(status_code=403, detail="Only the elder can change consent")
    actor_id = uuid.UUID(user["sub"])
    from app.db.models import BindingAuditEvent, CareCircleMember, FamilyBinding
    from app.db.session import async_session

    async with async_session() as db:
        binding = await db.get(FamilyBinding, binding_id)
        if binding is None or binding.elder_user_id != actor_id:
            raise HTTPException(status_code=404, detail="Binding not found")
        binding.status = "active" if body.approved else "revoked"
        binding.consent_status = "active" if body.approved else "revoked"
        binding.revoked_at = None if body.approved else datetime.utcnow()
        binding.version = (binding.version or 1) + 1
        member = (
            await db.execute(
                select(CareCircleMember).where(
                    CareCircleMember.household_id == binding.household_id,
                    CareCircleMember.user_id == binding.family_user_id,
                )
            )
        ).scalar_one_or_none()
        if member is not None:
            member.status = binding.status
        db.add(
            BindingAuditEvent(
                binding_id=binding.id,
                household_id=binding.household_id,
                actor_user_id=actor_id,
                event_type="binding.consent_approved" if body.approved else "binding.consent_revoked",
                payload_json={"version": binding.version},
            )
        )
        await db.commit()
    return {
        "binding_id": str(binding.id),
        "status": binding.status,
        "consent_status": binding.consent_status,
        "version": binding.version,
    }


@router.delete("/bindings/{binding_id}")
async def delete_care_circle_binding(
    binding_id: uuid.UUID,
    user: dict = Depends(get_current_user),
):
    result = await revoke_binding(binding_id, user)
    return {"revoked": result["status"] == "revoked", **result}


@router.get("/bindings/{binding_id}/audit")
async def list_binding_audit(binding_id: uuid.UUID, user: dict = Depends(get_current_user)):
    managed = await get_managed_household(user, permission="view_notifications")
    from app.db.models import BindingAuditEvent, FamilyBinding
    from app.db.session import async_session

    async with async_session() as db:
        binding = await db.get(FamilyBinding, binding_id)
        if binding is None or binding.elder_user_id != managed.elder_id:
            raise HTTPException(status_code=404, detail="Binding not found")
        rows = (
            await db.execute(
                select(BindingAuditEvent)
                .where(BindingAuditEvent.binding_id == binding_id)
                .order_by(BindingAuditEvent.created_at.asc())
            )
        ).scalars().all()
    return {
        "binding_id": str(binding_id),
        "items": [
            {
                "id": str(row.id),
                "event_type": row.event_type,
                "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
                "payload": row.payload_json or {},
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }
