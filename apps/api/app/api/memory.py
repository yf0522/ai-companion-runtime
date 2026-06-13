import uuid

from fastapi import APIRouter, Depends, HTTPException
from app.api.auth import get_current_user_uuid

router = APIRouter(tags=["memory"])


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
        from app.db.models import Memory
        from sqlalchemy import select

        async with async_session() as db:
            result = await db.execute(
                select(Memory)
                .where(Memory.user_id == user_id)
                .order_by(Memory.importance_score.desc())
                .limit(limit)
            )
            memories = result.scalars().all()
            return {
                "user_id": str(user_id),
                "memories": [
                    {
                        "id": str(m.id),
                        "content": m.content,
                        "type": m.memory_type,
                        "importance": m.importance_score,
                        "created_at": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in memories
                ],
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load memories: {e}")
