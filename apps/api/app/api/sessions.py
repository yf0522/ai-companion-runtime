from fastapi import APIRouter

router = APIRouter(tags=["sessions"])


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session details. Full implementation later."""
    return {
        "session_id": session_id,
        "status": "stub",
    }
