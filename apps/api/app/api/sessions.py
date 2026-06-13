import uuid

from fastapi import APIRouter, Depends, HTTPException
from app.api.auth import get_current_user_uuid

router = APIRouter(tags=["sessions"])


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user_id: uuid.UUID = Depends(get_current_user_uuid)):
    """Get session details — only if owned by the authenticated user."""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    try:
        from app.db.session import async_session
        from app.db.models import Session
        from sqlalchemy import select

        async with async_session() as db:
            result = await db.execute(
                select(Session).where(
                    Session.id == sid,
                    Session.user_id == user_id,
                )
            )
            session = result.scalar_one_or_none()
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            return {
                "session_id": str(session.id),
                "user_id": str(session.user_id),
                "status": session.status,
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "message_count": session.message_count,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load session: {e}")
