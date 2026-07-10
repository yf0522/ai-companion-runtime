from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select


@dataclass(frozen=True)
class ManagedHousehold:
    actor_id: uuid.UUID
    elder_id: uuid.UUID
    household_id: uuid.UUID | None
    role: str
    binding_id: uuid.UUID | None = None


async def get_managed_household(user: dict, *, permission: str) -> ManagedHousehold:
    from app.db.models import FamilyBinding
    from app.db.session import async_session

    role = user.get("role", "elder")
    try:
        actor_id = uuid.UUID(user["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid user identity in token") from exc

    if role == "elder":
        return ManagedHousehold(
            actor_id=actor_id,
            elder_id=actor_id,
            household_id=None,
            role=role,
        )

    async with async_session() as db:
        if role != "family":
            raise HTTPException(status_code=403, detail="Care circle access denied")

        binding = (
            await db.execute(
                select(FamilyBinding)
                .where(
                    FamilyBinding.family_user_id == actor_id,
                    FamilyBinding.status == "active",
                    FamilyBinding.consent_status == "active",
                    FamilyBinding.revoked_at.is_(None),
                )
                .order_by(FamilyBinding.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if binding is None:
            raise HTTPException(status_code=403, detail="No active elder binding found for this family account")
        if permission not in set(binding.permissions or []):
            raise HTTPException(status_code=403, detail="Family account lacks required permission")
        return ManagedHousehold(
            actor_id=actor_id,
            elder_id=binding.elder_user_id,
            household_id=binding.household_id,
            role=role,
            binding_id=binding.id,
        )


async def get_managed_elder_id(user: dict, *, permission: str) -> uuid.UUID:
    return (await get_managed_household(user, permission=permission)).elder_id
