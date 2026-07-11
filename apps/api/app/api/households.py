from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.api.auth import get_current_user
from app.api.family_auth import get_managed_household

router = APIRouter(prefix="/households", tags=["households"])

READINESS_ACTIVE_TASK_STATUSES = ("pending", "due", "snoozed")

DEFAULT_FAMILY_PERMISSIONS = ["view_reminders", "manage_reminders", "view_notifications"]


class HouseholdCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class InviteCreate(BaseModel):
    invitee_email: str | None = None
    permissions: list[str] = Field(default_factory=lambda: list(DEFAULT_FAMILY_PERMISSIONS))
    expires_in_hours: int = Field(default=72, ge=1, le=24 * 30)


class InviteAccept(BaseModel):
    token: str
    replay_nonce: str = Field(min_length=8, max_length=128)


class InviteDeny(BaseModel):
    token: str
    replay_nonce: str = Field(min_length=8, max_length=128)


class EscalationStepIn(BaseModel):
    step_order: int = Field(ge=1, le=20)
    action: str = Field(min_length=1, max_length=80)
    contact_point_id: uuid.UUID | None = None
    delay_seconds: int = Field(default=0, ge=0, le=86400)
    config: dict[str, Any] = Field(default_factory=dict)


class EscalationPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    steps: list[EscalationStepIn] = Field(default_factory=list)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _discover_households(*, query: str | None = None, limit: int = 50) -> list[dict]:
    from app.db.models import Household, User
    from app.db.session import async_session

    statement = (
        select(Household, User)
        .join(User, Household.elder_user_id == User.id)
        .where(Household.status == "active")
        .order_by(Household.updated_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    if query and query.strip():
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            or_(Household.name.ilike(pattern), User.username.ilike(pattern))
        )
    async with async_session() as db:
        rows = (await db.execute(statement)).all()
    return [
        {
            "id": str(household.id),
            "name": household.name,
            "elder_user_id": str(household.elder_user_id),
            "elder_name": elder.username,
            "status": household.status,
            "updated_at": household.updated_at.isoformat() if household.updated_at else None,
            "readiness_href": f"/api/households/{household.id}/readiness",
        }
        for household, elder in rows
    ]


async def _authorize_household_read(
    household_id: uuid.UUID,
    user: dict,
    *,
    permission: str = "view_notifications",
):
    from app.db.models import Household
    from app.db.session import async_session

    async with async_session() as db:
        household = await db.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail="Household not found")
    if user.get("role") == "operator":
        return household
    managed = await get_managed_household(user, permission=permission)
    if household.elder_user_id != managed.elder_id:
        raise HTTPException(status_code=404, detail="Household not found")
    if managed.role == "family" and managed.household_id != household_id:
        raise HTTPException(status_code=404, detail="Household not found")
    return household


async def _ensure_household(elder_id: uuid.UUID, name: str | None = None):
    from app.db.models import CareCircleMember, Household
    from app.db.session import async_session

    async with async_session() as db:
        household = (
            await db.execute(select(Household).where(Household.elder_user_id == elder_id))
        ).scalar_one_or_none()
        if household is not None:
            if name and household.name != name:
                household.name = name
                household.updated_at = datetime.utcnow()
                await db.commit()
            return household
        household = Household(elder_user_id=elder_id, name=name or "Household")
        db.add(household)
        await db.flush()
        db.add(
            CareCircleMember(
                household_id=household.id,
                user_id=elder_id,
                role="elder",
                status="active",
                permissions=["owner"],
            )
        )
        await db.commit()
        await db.refresh(household)
        return household


@router.post("")
async def create_household(body: HouseholdCreate, user: dict = Depends(get_current_user)):
    if user.get("role", "elder") != "elder":
        raise HTTPException(status_code=403, detail="Only elder users can create households")
    household = await _ensure_household(uuid.UUID(user["sub"]), body.name)
    return {"id": str(household.id), "elder_user_id": str(household.elder_user_id), "name": household.name}


@router.get("")
async def list_households_for_operator(
    query: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=50, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    if user.get("role") != "operator":
        raise HTTPException(status_code=403, detail="Operator role required")
    items = await _discover_households(query=query, limit=limit)
    return {
        "scope": "operator_household_discovery",
        "query": query,
        "items": items,
        "total": len(items),
    }


@router.get("/mine")
async def get_my_household(user: dict = Depends(get_current_user)):
    managed = await get_managed_household(user, permission="view_notifications")
    from app.db.models import Household
    from app.db.session import async_session

    household = None
    if managed.household_id:
        async with async_session() as db:
            household = await db.get(Household, managed.household_id)
    elif managed.role == "elder":
        household = await _ensure_household(managed.elder_id)
    if household is None:
        raise HTTPException(status_code=404, detail="Household not found")
    return {"id": str(household.id), "elder_user_id": str(household.elder_user_id), "name": household.name}


@router.post("/{household_id}/invites")
async def create_invite(
    household_id: uuid.UUID,
    body: InviteCreate,
    user: dict = Depends(get_current_user),
):
    managed = await get_managed_household(user, permission="view_notifications")
    if managed.role != "elder" or managed.household_id not in {None, household_id}:
        raise HTTPException(status_code=403, detail="Only the elder can invite family")
    household = await _ensure_household(managed.elder_id)
    if household.id != household_id:
        raise HTTPException(status_code=404, detail="Household not found")

    from app.db.models import HouseholdInvite
    from app.db.session import async_session

    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    invite = HouseholdInvite(
        household_id=household_id,
        elder_user_id=managed.elder_id,
        token_hash=_hash_token(token),
        invitee_email=body.invitee_email,
        permissions=body.permissions,
        status="pending",
        expires_at=now + timedelta(hours=body.expires_in_hours),
    )
    async with async_session() as db:
        db.add(invite)
        await db.commit()
        await db.refresh(invite)
    return {
        "invite_id": str(invite.id),
        "token": token,
        "status": invite.status,
        "expires_at": invite.expires_at.isoformat(),
    }


async def _consume_invite(token: str, actor_id: uuid.UUID, replay_nonce: str, target_status: str) -> dict[str, Any]:
    from app.db.models import BindingAuditEvent, CareCircleMember, FamilyBinding, HouseholdInvite
    from app.db.session import async_session

    now = datetime.utcnow()
    async with async_session() as db:
        invite = (
            await db.execute(
                select(HouseholdInvite)
                .where(HouseholdInvite.token_hash == _hash_token(token))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if invite is None:
            raise HTTPException(status_code=404, detail="Invite not found")
        if invite.replay_nonce == replay_nonce:
            if invite.status == target_status == "denied":
                return {"status": "denied", "invite_id": str(invite.id)}
            if invite.status == target_status == "accepted" and invite.accepted_by_user_id == actor_id:
                binding = (
                    await db.execute(
                        select(FamilyBinding).where(
                            FamilyBinding.household_id == invite.household_id,
                            FamilyBinding.family_user_id == actor_id,
                        )
                    )
                ).scalar_one_or_none()
                if binding is not None:
                    return {
                        "status": "accepted",
                        "binding_id": str(binding.id),
                        "household_id": str(invite.household_id),
                    }
            raise HTTPException(status_code=409, detail="Invite replay conflicts with the original result")
        if invite.status != "pending":
            raise HTTPException(status_code=409, detail=f"Invite is {invite.status}")
        if invite.expires_at <= now:
            invite.status = "expired"
            invite.updated_at = now
            await db.commit()
            raise HTTPException(status_code=410, detail="Invite expired")

        invite.replay_nonce = replay_nonce
        invite.updated_at = now
        if target_status == "denied":
            invite.status = "denied"
            invite.denied_at = now
            await db.commit()
            return {"status": "denied", "invite_id": str(invite.id)}

        invite.status = "accepted"
        invite.accepted_by_user_id = actor_id
        invite.accepted_at = now
        binding = FamilyBinding(
            household_id=invite.household_id,
            family_user_id=actor_id,
            elder_user_id=invite.elder_user_id,
            permissions=invite.permissions,
            status="active",
            consent_status="active",
            version=1,
        )
        db.add(binding)
        try:
            await db.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Family binding already exists") from exc
        db.add(
            CareCircleMember(
                household_id=invite.household_id,
                user_id=actor_id,
                role="family",
                status="active",
                permissions=invite.permissions,
            )
        )
        db.add(
            BindingAuditEvent(
                binding_id=binding.id,
                household_id=invite.household_id,
                actor_user_id=actor_id,
                event_type="binding.accepted",
                payload_json={"invite_id": str(invite.id), "permissions": invite.permissions or []},
            )
        )
        await db.commit()
        return {"status": "accepted", "binding_id": str(binding.id), "household_id": str(invite.household_id)}


@router.post("/invites/accept")
async def accept_invite(body: InviteAccept, user: dict = Depends(get_current_user)):
    if user.get("role") != "family":
        raise HTTPException(status_code=403, detail="Family account required to accept invite")
    return await _consume_invite(body.token, uuid.UUID(user["sub"]), body.replay_nonce, "accepted")


@router.post("/invites/deny")
async def deny_invite(body: InviteDeny, user: dict = Depends(get_current_user)):
    return await _consume_invite(body.token, uuid.UUID(user["sub"]), body.replay_nonce, "denied")


@router.post("/bindings/{binding_id}/revoke")
async def revoke_binding(binding_id: uuid.UUID, user: dict = Depends(get_current_user)):
    from app.db.models import BindingAuditEvent, FamilyBinding
    from app.db.session import async_session

    managed = await get_managed_household(user, permission="view_notifications")
    now = datetime.utcnow()
    async with async_session() as db:
        binding = await db.get(FamilyBinding, binding_id)
        if binding is None or binding.elder_user_id != managed.elder_id:
            raise HTTPException(status_code=404, detail="Binding not found")
        if managed.role != "elder" and managed.actor_id != binding.family_user_id:
            raise HTTPException(status_code=403, detail="Binding revoke denied")
        binding.status = "revoked"
        binding.consent_status = "revoked"
        binding.revoked_at = now
        binding.version = (binding.version or 1) + 1
        binding.updated_at = now
        db.add(
            BindingAuditEvent(
                binding_id=binding.id,
                household_id=binding.household_id,
                actor_user_id=managed.actor_id,
                event_type="binding.revoked",
                payload_json={"version": binding.version},
            )
        )
        await db.commit()
    return {"status": "revoked", "binding_id": str(binding_id)}


async def _household_readiness(household_id: uuid.UUID, user: dict) -> dict:
    role = user.get("role", "elder")
    from app.db.models import Household
    from app.db.session import async_session

    async with async_session() as db:
        household = await db.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail="Household not found")
    if role == "operator":
        elder_id = household.elder_user_id
    else:
        managed = await get_managed_household(user, permission="view_notifications")
        if household.elder_user_id != managed.elder_id:
            raise HTTPException(status_code=404, detail="Household not found")
        if managed.role == "family" and managed.household_id != household_id:
            raise HTTPException(status_code=404, detail="Household not found")
        elder_id = managed.elder_id

    from app.db.models import (
        CareTask,
        ContactPoint,
        EscalationPolicy,
        FamilyBinding,
        NotificationOutbox,
    )
    from app.db.device_models import Device
    from app.db.session import async_session

    async with async_session() as db:
        active_binding = (
            await db.execute(
                select(func.count())
                .select_from(FamilyBinding)
                .where(
                    FamilyBinding.household_id == household_id,
                    FamilyBinding.status == "active",
                    FamilyBinding.consent_status == "active",
                    FamilyBinding.revoked_at.is_(None),
                )
            )
        ).scalar_one()
        verified_contact = (
            await db.execute(
                select(func.count())
                .select_from(ContactPoint)
                .where(
                    ContactPoint.household_id == household_id,
                    ContactPoint.status == "active",
                    ContactPoint.verification_state == "verified",
                    ContactPoint.revoked_at.is_(None),
                )
            )
        ).scalar_one()
        provider_delivery = (
            await db.execute(
                select(func.count())
                .select_from(NotificationOutbox)
                .where(
                    NotificationOutbox.user_id == elder_id,
                    NotificationOutbox.provider == "signed_webhook",
                    NotificationOutbox.state.in_(["accepted", "delivered", "read"]),
                )
            )
        ).scalar_one()
        active_device = (
            await db.execute(
                select(func.count())
                .select_from(Device)
                .where(
                    Device.user_id == elder_id,
                    Device.status == "enrolled",
                    Device.credential_state == "active",
                    Device.revoked_at.is_(None),
                )
            )
        ).scalar_one()
        active_task = (
            await db.execute(
                select(func.count())
                .select_from(CareTask)
                .where(
                    CareTask.user_id == elder_id,
                    CareTask.status.in_(READINESS_ACTIVE_TASK_STATUSES),
                )
            )
        ).scalar_one()
        active_policy = (
            await db.execute(
                select(func.count())
                .select_from(EscalationPolicy)
                .where(EscalationPolicy.household_id == household_id, EscalationPolicy.status == "active")
            )
        ).scalar_one()

    from app.runtime.readiness import READY, assess_platform_readiness

    platform = await assess_platform_readiness()
    check_values = {
        "platform": platform["status"] == READY,
        "active_consent_binding": active_binding > 0,
        "verified_contact": verified_contact > 0,
        "production_provider_delivery_test": provider_delivery > 0,
        "enrolled_active_device": active_device > 0,
        "active_care_task": active_task > 0,
        "active_escalation_policy": active_policy > 0,
    }
    labels = {
        "platform": "平台服务可用",
        "active_consent_binding": "家属授权已生效",
        "verified_contact": "紧急联系方式已验证",
        "production_provider_delivery_test": "通知通道已送达验证",
        "enrolled_active_device": "陪伴设备已激活",
        "active_care_task": "至少有一项待办照护任务",
        "active_escalation_policy": "升级处置规则已启用",
    }
    details = {
        "platform": f"平台当前状态：{platform['status']}",
        "active_consent_binding": "存在长辈授权且未撤销的家属绑定",
        "verified_contact": "至少一个未撤销的联系方式已完成验证",
        "production_provider_delivery_test": "真实通知提供方已有 accepted、delivered 或 read 回执",
        "enrolled_active_device": "至少一个未撤销的设备凭据处于激活状态",
        "active_care_task": "至少一项 CareTask 可继续执行或稍后提醒",
        "active_escalation_policy": "家庭已启用一版升级处置规则",
    }
    owners = {
        "platform": "平台运营",
        "active_consent_binding": "长辈",
        "verified_contact": "家庭管理员",
        "production_provider_delivery_test": "平台运营",
        "enrolled_active_device": "家庭管理员",
        "active_care_task": "家庭成员",
        "active_escalation_policy": "长辈",
    }
    actions = {
        "platform": "检查依赖服务与 worker 配置",
        "active_consent_binding": "由长辈邀请家属并完成授权",
        "verified_contact": "添加联系方式并完成验证码验证",
        "production_provider_delivery_test": "发送一次真实测试通知并等待回执",
        "enrolled_active_device": "完成设备注册与凭据激活",
        "active_care_task": "创建一项近期照护任务",
        "active_escalation_policy": "由长辈创建并启用升级处置规则",
    }
    evidence = {
        "platform": {"platform_status": platform["status"]},
        "active_consent_binding": {"active_binding_count": active_binding},
        "verified_contact": {"verified_contact_count": verified_contact},
        "production_provider_delivery_test": {"confirmed_delivery_count": provider_delivery},
        "enrolled_active_device": {"active_device_count": active_device},
        "active_care_task": {"active_task_count": active_task},
        "active_escalation_policy": {"active_policy_count": active_policy},
    }
    assessed_at = datetime.utcnow().isoformat()
    checks = [
        {
            "key": key,
            "label": labels[key],
            "status": "ready" if value else "blocked",
            "detail": details[key],
            "required": True,
            "owner": owners[key],
            "action": None if value else actions[key],
            "evidence": evidence[key],
            "evidence_at": assessed_at,
        }
        for key, value in check_values.items()
    ]
    ready = all(check_values.values())
    next_action = next(
        (actions[key] for key, value in check_values.items() if not value),
        None,
    )
    return {
        "household_id": str(household_id),
        "status": "ready" if ready else "blocked",
        "checks": checks,
        "next_action": next_action,
        "updated_at": assessed_at,
    }


@router.get("/readiness")
async def my_household_readiness(
    household_id: uuid.UUID | None = Query(default=None),
    query: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=50, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    if user.get("role") == "operator":
        if household_id is not None:
            return await _household_readiness(household_id, user)
        items = await _discover_households(query=query, limit=limit)
        return {
            "scope": "operator_household_selection",
            "household_required": True,
            "items": items,
            "total": len(items),
        }
    managed = await get_managed_household(user, permission="view_notifications")
    household_id = managed.household_id
    if household_id is None and managed.role == "elder":
        household_id = (await _ensure_household(managed.elder_id)).id
    if household_id is None:
        raise HTTPException(status_code=404, detail="Household not found")
    return await _household_readiness(household_id, user)


@router.get("/{household_id}/readiness")
async def household_readiness(household_id: uuid.UUID, user: dict = Depends(get_current_user)):
    return await _household_readiness(household_id, user)


@router.get("/{household_id}/escalation-policies")
async def list_escalation_policies(
    household_id: uuid.UUID,
    include_superseded: bool = Query(default=False),
    user: dict = Depends(get_current_user),
):
    await _authorize_household_read(household_id, user)
    from app.db.models import EscalationPolicy, EscalationStep
    from app.db.session import async_session

    statement = select(EscalationPolicy).where(
        EscalationPolicy.household_id == household_id
    )
    if not include_superseded:
        statement = statement.where(EscalationPolicy.status == "active")
    statement = statement.order_by(EscalationPolicy.version.desc())
    async with async_session() as db:
        policies = (await db.execute(statement)).scalars().all()
        policy_ids = [row.id for row in policies]
        steps = []
        if policy_ids:
            steps = (
                await db.execute(
                    select(EscalationStep)
                    .where(EscalationStep.policy_id.in_(policy_ids))
                    .order_by(EscalationStep.policy_id, EscalationStep.step_order)
                )
            ).scalars().all()
    steps_by_policy: dict[uuid.UUID, list] = {}
    for step in steps:
        steps_by_policy.setdefault(step.policy_id, []).append(step)
    items = [
        {
            "resource_type": "escalation_policy",
            "id": str(policy.id),
            "household_id": str(policy.household_id),
            "name": policy.name,
            "version": policy.version,
            "status": policy.status,
            "created_at": policy.created_at.isoformat() if policy.created_at else None,
            "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
            "steps": [
                {
                    "resource_type": "escalation_step",
                    "id": str(step.id),
                    "step_order": step.step_order,
                    "action": step.action,
                    "contact_point_id": (
                        str(step.contact_point_id) if step.contact_point_id else None
                    ),
                    "delay_seconds": step.delay_seconds,
                    "config": step.config_json or {},
                }
                for step in steps_by_policy.get(policy.id, [])
            ],
        }
        for policy in policies
    ]
    return {"household_id": str(household_id), "items": items, "total": len(items)}


@router.post("/{household_id}/escalation-policies")
async def create_escalation_policy(
    household_id: uuid.UUID,
    body: EscalationPolicyCreate,
    user: dict = Depends(get_current_user),
):
    managed = await get_managed_household(user, permission="manage_reminders")
    if managed.role != "elder" or managed.elder_id != uuid.UUID(user["sub"]):
        raise HTTPException(status_code=403, detail="Only the elder can manage escalation policies")

    from app.db.models import ContactPoint, EscalationPolicy, EscalationStep
    from app.db.session import async_session

    async with async_session() as db:
        household = await _ensure_household(managed.elder_id)
        if household.id != household_id:
            raise HTTPException(status_code=404, detail="Household not found")
        latest_version = (
            await db.execute(
                select(func.max(EscalationPolicy.version)).where(
                    EscalationPolicy.household_id == household_id
                )
            )
        ).scalar_one()
        version = int(latest_version or 0) + 1
        await db.execute(
            EscalationPolicy.__table__.update()
            .where(EscalationPolicy.household_id == household_id, EscalationPolicy.status == "active")
            .values(status="superseded", updated_at=datetime.utcnow())
        )
        policy = EscalationPolicy(
            household_id=household_id,
            name=body.name,
            version=version,
            status="active",
        )
        db.add(policy)
        await db.flush()
        seen_orders: set[int] = set()
        for step in body.steps:
            if step.step_order in seen_orders:
                raise HTTPException(status_code=422, detail="Duplicate escalation step_order")
            seen_orders.add(step.step_order)
            if step.contact_point_id:
                contact = await db.get(ContactPoint, step.contact_point_id)
                if contact is None or contact.household_id != household_id:
                    raise HTTPException(status_code=404, detail="Escalation contact point not found")
            db.add(
                EscalationStep(
                    policy_id=policy.id,
                    step_order=step.step_order,
                    action=step.action,
                    contact_point_id=step.contact_point_id,
                    delay_seconds=step.delay_seconds,
                    config_json=step.config,
                )
            )
        await db.commit()
        await db.refresh(policy)
    return {
        "id": str(policy.id),
        "household_id": str(household_id),
        "version": policy.version,
        "status": policy.status,
        "steps": [step.model_dump(mode="json") for step in body.steps],
    }
