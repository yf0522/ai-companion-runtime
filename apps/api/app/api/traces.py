from fastapi import APIRouter, HTTPException
from app.observability.trace_service import TraceService

router = APIRouter(tags=["traces"])
trace_service = TraceService()


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str):
    result = await trace_service.get_trace(trace_id)
    if not result:
        raise HTTPException(status_code=404, detail="Trace not found")
    return result


@router.get("/traces")
async def list_traces(user_id: str = "", limit: int = 20, offset: int = 0):
    try:
        from app.db.session import async_session
        from app.db.models import TraceEvent
        from sqlalchemy import select, func

        async with async_session() as db:
            query = select(
                TraceEvent.trace_id,
                func.min(TraceEvent.start_time).label("started_at"),
                func.count(TraceEvent.id).label("event_count"),
            ).group_by(TraceEvent.trace_id)

            if user_id:
                query = query.where(TraceEvent.user_id == user_id)

            query = query.order_by(func.min(TraceEvent.start_time).desc())
            query = query.offset(offset).limit(limit)

            result = await db.execute(query)
            rows = result.all()

            return {
                "traces": [
                    {
                        "trace_id": row.trace_id,
                        "started_at": row.started_at.isoformat() if row.started_at else None,
                        "event_count": row.event_count,
                    }
                    for row in rows
                ],
                "limit": limit,
                "offset": offset,
            }
    except Exception as e:
        return {"traces": [], "limit": limit, "offset": offset, "error": str(e)}
