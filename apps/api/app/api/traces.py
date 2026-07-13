from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select

from app.api.auth import get_current_user
from app.observability.trace_service import TraceService

router = APIRouter(tags=["traces"])
trace_service = TraceService()


def _trace_status(event_count: int | None, failed_event_count: int | None) -> str:
    if event_count is None:
        return "unknown"
    return "failed" if (failed_event_count or 0) > 0 else "completed"


async def _operator_trace_cases(db, trace_id: str):
    """Return only lawful OperatorCase relations for an operator trace view."""
    from app.db.models import OperatorCase, SafetyDecision

    return (
        await db.execute(
            select(OperatorCase, SafetyDecision)
            .join(SafetyDecision, OperatorCase.safety_decision_id == SafetyDecision.id)
            .where(SafetyDecision.trace_id == trace_id)
            .order_by(OperatorCase.created_at.asc())
        )
    ).all()


def _operator_trace_page_statement(*, limit: int, offset: int):
    """Page distinct case-authorized traces before loading their case relations."""
    from app.db.models import OperatorCase, SafetyDecision

    latest_case_at = func.max(OperatorCase.created_at).label("latest_case_at")
    return (
        select(SafetyDecision.trace_id, latest_case_at)
        .select_from(OperatorCase)
        .join(SafetyDecision, OperatorCase.safety_decision_id == SafetyDecision.id)
        .where(SafetyDecision.trace_id.is_not(None))
        .group_by(SafetyDecision.trace_id)
        .order_by(latest_case_at.desc())
        .offset(offset)
        .limit(limit)
    )


def _operator_trace_total_statement():
    """Count distinct traces that are lawfully connected to operator cases."""
    from app.db.models import OperatorCase, SafetyDecision

    return (
        select(func.count(func.distinct(SafetyDecision.trace_id)))
        .select_from(OperatorCase)
        .join(SafetyDecision, OperatorCase.safety_decision_id == SafetyDecision.id)
        .where(SafetyDecision.trace_id.is_not(None))
    )


def _case_authorization(case_rows) -> dict:
    cases = [row[0] for row in case_rows]
    return {
        "scope": "operator_case",
        "case_id": str(cases[0].id) if cases else None,
        "case_ids": [str(row.id) for row in cases],
        "audited": bool(cases),
    }


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str, user: dict = Depends(get_current_user)):
    result = await trace_service.get_trace(trace_id)
    if not result:
        raise HTTPException(status_code=404, detail="Trace not found")

    actor_id = uuid.UUID(user["sub"])
    if user.get("role") != "operator":
        if result.get("user_id") != str(actor_id):
            raise HTTPException(status_code=404, detail="Trace not found")
        return {
            **result,
            "authorization": {
                "scope": "self",
                "case_id": None,
                "case_ids": [],
                "audited": False,
            },
        }

    from app.db.models import CaseActivity
    from app.db.session import async_session

    async with async_session() as db:
        case_rows = await _operator_trace_cases(db, trace_id)
        if not case_rows:
            # Do not disclose whether a non-case trace exists.
            raise HTTPException(status_code=404, detail="Trace not found")
        viewed_at = datetime.utcnow()
        for operator_case, _decision in case_rows:
            db.add(
                CaseActivity(
                    case_id=operator_case.id,
                    actor_user_id=actor_id,
                    activity_type="trace_viewed",
                    payload_json={
                        "summary": "Operator viewed case-authorized trace evidence",
                        "actor_type": "operator",
                        "trace_id": trace_id,
                    },
                    created_at=viewed_at,
                )
            )
        await db.commit()
    return {**result, "authorization": _case_authorization(case_rows)}


@router.get("/traces")
async def list_traces(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
):
    """List self-owned traces or traces connected to an operator case."""
    from app.db.models import OperatorCase, SafetyDecision, TraceEvent
    from app.db.session import async_session

    actor_id = uuid.UUID(user["sub"])
    failed_count = func.sum(
        case((TraceEvent.status.in_(["error", "failed", "timeout"]), 1), else_=0)
    ).label("failed_event_count")

    try:
        async with async_session() as db:
            if user.get("role") != "operator":
                rows = (
                    await db.execute(
                        select(
                            TraceEvent.trace_id,
                            func.min(TraceEvent.start_time).label("started_at"),
                            func.count(TraceEvent.id).label("event_count"),
                            failed_count,
                        )
                        .where(TraceEvent.user_id == actor_id)
                        .group_by(TraceEvent.trace_id)
                        .order_by(func.min(TraceEvent.start_time).desc())
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
                items = [
                    {
                        "trace_id": row.trace_id,
                        "started_at": row.started_at.isoformat() if row.started_at else None,
                        "event_count": row.event_count,
                        "failed_event_count": row.failed_event_count,
                        "status": _trace_status(row.event_count, row.failed_event_count),
                        "user_id": str(actor_id),
                        "case_id": None,
                        "case_ids": [],
                        "case_status": None,
                        "severity": None,
                    }
                    for row in rows
                ]
                scope = "self"
                total = len(items)
            else:
                trace_page = (
                    await db.execute(
                        _operator_trace_page_statement(limit=limit, offset=offset)
                    )
                ).all()
                trace_ids = [row.trace_id for row in trace_page]
                total = (await db.execute(_operator_trace_total_statement())).scalar_one()
                relations = []
                if trace_ids:
                    relations = (
                        await db.execute(
                            select(OperatorCase, SafetyDecision)
                            .join(
                                SafetyDecision,
                                OperatorCase.safety_decision_id == SafetyDecision.id,
                            )
                            .where(SafetyDecision.trace_id.in_(trace_ids))
                            .order_by(OperatorCase.created_at.desc())
                        )
                    ).all()
                by_trace: dict[str, list] = defaultdict(list)
                decision_by_trace = {}
                for operator_case, decision in relations:
                    by_trace[decision.trace_id].append(operator_case)
                    decision_by_trace[decision.trace_id] = decision
                aggregate_by_trace = {}
                if trace_ids:
                    aggregate_rows = (
                        await db.execute(
                            select(
                                TraceEvent.trace_id,
                                func.min(TraceEvent.start_time).label("started_at"),
                                func.count(TraceEvent.id).label("event_count"),
                                failed_count,
                            )
                            .where(TraceEvent.trace_id.in_(trace_ids))
                            .group_by(TraceEvent.trace_id)
                        )
                    ).all()
                    aggregate_by_trace = {row.trace_id: row for row in aggregate_rows}
                items = []
                for trace_id in trace_ids:
                    cases = by_trace[trace_id]
                    aggregate = aggregate_by_trace.get(trace_id)
                    decision = decision_by_trace[trace_id]
                    items.append(
                        {
                            "trace_id": trace_id,
                            "started_at": (
                                aggregate.started_at.isoformat()
                                if aggregate is not None and aggregate.started_at
                                else None
                            ),
                            "event_count": aggregate.event_count if aggregate is not None else None,
                            "failed_event_count": (
                                aggregate.failed_event_count if aggregate is not None else None
                            ),
                            "status": _trace_status(
                                aggregate.event_count if aggregate is not None else None,
                                aggregate.failed_event_count if aggregate is not None else None,
                            ),
                            "user_id": str(decision.user_id),
                            "case_id": str(cases[0].id),
                            "case_ids": [str(row.id) for row in cases],
                            "case_status": cases[0].status,
                            "severity": cases[0].severity,
                        }
                    )
                scope = "operator_case"

        return {
            "contract_version": "trace-list.v2",
            "scope": scope,
            "items": items,
            "traces": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list traces: {exc}") from exc
