import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, select

from app.api.auth import get_current_user_uuid

router = APIRouter(tags=["memory"])


class MemoryCorrectionRequest(BaseModel):
    corrected_content: str = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, max_length=500)


class ReflectionAcceptanceRequest(BaseModel):
    proposal_id: uuid.UUID


class MemoryConsentRequest(BaseModel):
    approved: bool


@router.get("/memory/profile")
async def get_user_profile(user_id: uuid.UUID = Depends(get_current_user_uuid)):
    """Get authenticated user's profile."""
    try:
        from app.db.session import async_session
        from app.db.models import UserProfileModel
        from sqlalchemy import select

        async with async_session() as db:
            result = await db.execute(
                select(UserProfileModel).where(UserProfileModel.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile:
                return {"user_id": str(user_id), "profile": profile.profile_json, "version": profile.version}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load profile: {e}")
    return {"user_id": str(user_id), "profile": {}, "version": 0}


@router.get("/memory/memories")
async def get_memories(
    limit: int = 20,
    user_id: uuid.UUID = Depends(get_current_user_uuid),
):
    """Get authenticated user's stored memories."""
    try:
        from app.db.session import async_session
        from app.memory.lifecycle import select_retrievable_memories

        async with async_session() as db:
            memories = await select_retrievable_memories(db, user_id=user_id, limit=limit)
            return {
                "user_id": str(user_id),
                "memories": memories,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load memories: {e}")


@router.patch("/memory/memories/{memory_id}/correction")
async def correct_user_memory(
    memory_id: uuid.UUID,
    request: MemoryCorrectionRequest,
    user_id: uuid.UUID = Depends(get_current_user_uuid),
):
    try:
        from app.db.session import async_session
        from app.memory.lifecycle import correct_memory

        async with async_session() as db:
            applied = await correct_memory(
                db,
                memory_id=memory_id,
                user_id=user_id,
                requested_by=user_id,
                corrected_content=request.corrected_content,
                reason=request.reason,
            )
            if not applied:
                raise HTTPException(status_code=404, detail="Memory not found or not correctable")
            await db.commit()
            return {"memory_id": str(memory_id), "correction_state": "corrected"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to correct memory: {e}")


@router.post("/memory/memories/{memory_id}/consent")
async def decide_user_memory_consent(
    memory_id: uuid.UUID,
    request: MemoryConsentRequest,
    user_id: uuid.UUID = Depends(get_current_user_uuid),
):
    """Approve or reject an authenticated owner's pending memory."""
    try:
        from app.db.session import async_session
        from app.memory.lifecycle import decide_memory_consent

        async with async_session() as db:
            decision = await decide_memory_consent(
                db,
                memory_id=memory_id,
                user_id=user_id,
                approved=request.approved,
            )
            if decision is None:
                raise HTTPException(status_code=404, detail="Memory not found")
            await db.commit()
            return decision
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update memory consent: {e}")


@router.delete("/memory/memories/{memory_id}")
async def delete_user_memory(
    memory_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_uuid),
):
    try:
        from app.db.session import async_session
        from app.memory.lifecycle import delete_memory

        async with async_session() as db:
            deleted = await delete_memory(db, memory_id=memory_id, user_id=user_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Memory not found or already deleted")
            await db.commit()
            return {
                "memory_id": str(memory_id),
                "deletion_state": "deleted",
                "embedding_state": "deleted",
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete memory: {e}")


@router.post("/memory/reflection/accept")
async def accept_reflection(
    request: ReflectionAcceptanceRequest,
    user_id: uuid.UUID = Depends(get_current_user_uuid),
):
    try:
        from app.workers.reflection_worker import _accept_reflection_proposal

        accepted = await _accept_reflection_proposal(str(request.proposal_id), str(user_id))
        if not accepted:
            raise HTTPException(status_code=404, detail="Reflection proposal not found")
        return {"proposal_id": str(request.proposal_id), "status": "accepted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to accept reflection proposal: {e}")


@router.get("/memory/family-summary/{elder_user_id}")
async def get_family_memory_summary(
    elder_user_id: uuid.UUID,
    family_user_id: uuid.UUID = Depends(get_current_user_uuid),
):
    """Return a privacy-safe family summary built from care outcomes, not transcripts."""
    try:
        from app.db.models import CareTask, FamilyBinding
        from app.db.session import async_session
        from app.memory.lifecycle import build_privacy_safe_family_summary

        async with async_session() as db:
            binding_result = await db.execute(
                select(FamilyBinding).where(
                    FamilyBinding.family_user_id == family_user_id,
                    FamilyBinding.elder_user_id == elder_user_id,
                )
            )
            binding = binding_result.scalar_one_or_none()
            permissions = set(binding.permissions or []) if binding else set()
            if "view_reminders" not in permissions and "view_notifications" not in permissions:
                raise HTTPException(status_code=403, detail="Not authorized for elder care summary")

            result = await db.execute(
                select(CareTask)
                .where(
                    and_(
                        CareTask.user_id == elder_user_id,
                        CareTask.status.in_(
                            [
                                "done",
                                "completed",
                                "acknowledged",
                                "missed",
                                "failed",
                                "expired",
                                "cancelled",
                                "snoozed",
                            ]
                        ),
                    )
                )
                .order_by(CareTask.updated_at.desc())
                .limit(20)
            )
            tasks = result.scalars().all()
            outcomes = [
                {
                    "id": task.id,
                    "task_type": task.task_type,
                    "status": task.status,
                    "due_at": task.due_at,
                    "completed_at": task.completed_at,
                }
                for task in tasks
            ]
            return {
                "elder_user_id": str(elder_user_id),
                "family_user_id": str(family_user_id),
                "summary": build_privacy_safe_family_summary(outcomes),
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build family summary: {e}")


@router.get("/memory/family-summary")
async def get_current_family_memory_summary(
    family_user_id: uuid.UUID = Depends(get_current_user_uuid),
):
    """Resolve the current family binding and return care outcomes only."""
    try:
        from app.db.models import FamilyBinding
        from app.db.session import async_session

        async with async_session() as db:
            result = await db.execute(
                select(FamilyBinding)
                .where(FamilyBinding.family_user_id == family_user_id)
                .order_by(FamilyBinding.created_at.desc())
                .limit(1)
            )
            binding = result.scalar_one_or_none()
            if not binding:
                raise HTTPException(status_code=403, detail="No elder binding found")
        return await get_family_memory_summary(binding.elder_user_id, family_user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve family summary: {e}")
