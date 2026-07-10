"""Canonical CareTask HTTP API.

CareTask is the care-domain source of truth. Reminder rows are scheduling
projection rows managed through the CareTask service, not a competing API model.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.auth import get_current_user
from app.api.family_auth import get_managed_elder_id
from app.tools import caretask_service as svc

router = APIRouter(tags=["care-tasks"])


class IdempotencyClaimState(str, Enum):
    WON = "won"
    REPLAY = "replay"


class IdempotencyClaim(BaseModel):
    state: IdempotencyClaimState
    record_id: uuid.UUID | None = None
    response: dict[str, Any] | None = None


class CareTaskCreate(BaseModel):
    title: str
    task_type: str = "medication"
    due_at: datetime | None = None
    notes: str | None = None
    schedule_type: Literal["once", "daily", "weekly", "interval"] | None = None
    query: str | None = None


class CareTaskUpdate(BaseModel):
    title: str | None = None
    due_at: datetime | None = None
    notes: str | None = None
    expected_version: int = Field(..., ge=1)


class CareTaskVersionedAction(BaseModel):
    expected_version: int = Field(..., ge=1)


class CareTaskSnooze(CareTaskVersionedAction):
    minutes: int = Field(default=30, ge=1, le=1440)


class CareTaskClarify(BaseModel):
    decision: Literal["use_existing", "create_new"]
    task_id: str | None = None
    proposed: CareTaskCreate | None = None


_get_managed_elder_id = get_managed_elder_id


def _request_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _claim_idempotency(
    *,
    user_id: uuid.UUID,
    key: str,
    operation: str,
    request_hash: str,
) -> IdempotencyClaim:
    from app.db.models import IdempotencyRecord
    from app.db.session import async_session

    async with async_session() as db:
        record = IdempotencyRecord(
            user_id=user_id,
            key=key,
            operation=operation,
            resource_type="care_task",
            request_hash=request_hash,
            response_json={},
            error_json={},
            status="in_progress",
            status_code=202,
        )
        db.add(record)
        try:
            await db.commit()
            return IdempotencyClaim(state=IdempotencyClaimState.WON, record_id=record.id)
        except IntegrityError:
            await db.rollback()
            result = await db.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.user_id == user_id,
                    IdempotencyRecord.key == key,
                    IdempotencyRecord.operation == operation,
                )
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                raise HTTPException(status_code=503, detail="Idempotency claim could not be recovered")
            if existing.request_hash != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key was reused with a different request",
                )
            if existing.status == "completed":
                response = dict(existing.response_json or {})
                response["idempotent_replay"] = True
                return IdempotencyClaim(state=IdempotencyClaimState.REPLAY, response=response)
            if existing.status == "failed":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "idempotency_previous_failed",
                        "status_code": existing.status_code,
                        "error": existing.error_json or {},
                    },
                )
            raise HTTPException(
                status_code=409,
                detail={"code": "idempotency_in_progress", "operation": operation},
            )


async def _finish_idempotency(
    *,
    record_id: uuid.UUID,
    resource_id: uuid.UUID | None,
    response: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    status_code: int,
) -> None:
    from app.db.models import IdempotencyRecord
    from app.db.session import async_session

    async with async_session() as db:
        record = await db.get(IdempotencyRecord, record_id)
        if record is None:
            return
        record.resource_id = resource_id
        record.status = "completed" if response is not None else "failed"
        record.response_json = response or {}
        record.error_json = error or {}
        record.status_code = status_code
        record.updated_at = datetime.utcnow()
        await db.commit()


async def _run_idempotent(
    *,
    actor_id: uuid.UUID,
    key: str | None,
    operation: str,
    payload: dict[str, Any],
    action: Any,
) -> dict[str, Any]:
    if not key or not key.strip():
        raise HTTPException(status_code=428, detail="Idempotency-Key header is required for CareTask mutations")
    clean_key = key.strip()
    digest = _request_hash(payload)
    claim = await _claim_idempotency(
        user_id=actor_id,
        key=clean_key,
        operation=operation,
        request_hash=digest,
    )
    if claim.state == IdempotencyClaimState.REPLAY:
        return claim.response or {}
    if claim.record_id is None:
        raise HTTPException(status_code=503, detail="Idempotency claim is missing")

    try:
        response = await action(clean_key)
    except HTTPException as exc:
        await _finish_idempotency(
            record_id=claim.record_id,
            resource_id=None,
            error={"detail": exc.detail},
            status_code=exc.status_code,
        )
        raise
    except Exception as exc:
        await _finish_idempotency(
            record_id=claim.record_id,
            resource_id=None,
            error={"detail": str(exc)},
            status_code=500,
        )
        raise
    resource_id: uuid.UUID | None = None
    if response.get("id"):
        try:
            resource_id = uuid.UUID(str(response["id"]))
        except (ValueError, TypeError):
            resource_id = None
    await _finish_idempotency(
        record_id=claim.record_id,
        resource_id=resource_id,
        response=response,
        status_code=200,
    )
    return response


def _stale_version_error(exc: svc.StaleCareTaskVersionError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "stale_version",
            "expected_version": exc.expected_version,
            "current_version": exc.current_version,
        },
    )


@router.get("/care-tasks")
async def list_care_tasks(
    include_terminal: bool = False,
    limit: int = 50,
    user: dict = Depends(get_current_user),
):
    elder_id = await _get_managed_elder_id(user, permission="view_reminders")
    rows = await svc.list_care_tasks(
        user_id=str(elder_id),
        include_terminal=include_terminal,
        limit=max(1, min(limit, 100)),
    )
    return {"user_id": str(elder_id), "items": rows, "total": len(rows)}


@router.post("/care-tasks")
async def create_care_task(
    body: CareTaskCreate,
    user: dict = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    elder_id = await _get_managed_elder_id(user, permission="manage_reminders")
    actor_id = uuid.UUID(user["sub"])
    payload = body.model_dump(mode="json")

    async def action(clean_key: str) -> dict[str, Any]:
        data = await svc.create_care_task(
            user_id=str(elder_id),
            title=body.title,
            task_type=body.task_type,
            due_at=body.due_at,
            notes=body.notes,
            created_by=user.get("role", "elder"),
            link_reminder=True,
            schedule_type=body.schedule_type,
            query=body.query,
            idempotency_key=clean_key,
        )
        data["canonical"] = "CareTask"
        return data

    return await _run_idempotent(
        actor_id=actor_id,
        key=idempotency_key,
        operation="caretask:create",
        payload=payload,
        action=action,
    )


@router.patch("/care-tasks/{task_id}")
async def update_care_task(
    task_id: str,
    body: CareTaskUpdate,
    user: dict = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    elder_id = await _get_managed_elder_id(user, permission="manage_reminders")
    actor_id = uuid.UUID(user["sub"])
    payload = {"task_id": task_id, **body.model_dump(mode="json")}

    async def action(_clean_key: str) -> dict[str, Any]:
        try:
            data = await svc.update_care_task(
                user_id=str(elder_id),
                task_id=task_id,
                expected_version=body.expected_version,
                title=body.title,
                due_at=body.due_at,
                notes=body.notes,
            )
        except svc.StaleCareTaskVersionError as exc:
            raise _stale_version_error(exc) from exc
        except LookupError:
            raise HTTPException(status_code=404, detail="CareTask not found")
        except ValueError:
            raise HTTPException(status_code=404, detail="CareTask not found")
        else:
            data["canonical"] = "CareTask"
            return data

    return await _run_idempotent(
        actor_id=actor_id,
        key=idempotency_key,
        operation=f"caretask:update:{task_id}",
        payload=payload,
        action=action,
    )


@router.post("/care-tasks/{task_id}/complete")
async def complete_care_task(
    task_id: str,
    body: CareTaskVersionedAction,
    user: dict = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    elder_id = await _get_managed_elder_id(user, permission="manage_reminders")
    actor_id = uuid.UUID(user["sub"])
    payload = {"task_id": task_id, **body.model_dump(mode="json")}

    async def action(_clean_key: str) -> dict[str, Any]:
        try:
            data = await svc.complete_care_task(
                user_id=str(elder_id),
                task_id=task_id,
                expected_version=body.expected_version,
            )
        except svc.StaleCareTaskVersionError as exc:
            raise _stale_version_error(exc) from exc
        except LookupError:
            raise HTTPException(status_code=404, detail="CareTask not found")
        data["canonical"] = "CareTask"
        return data

    return await _run_idempotent(
        actor_id=actor_id,
        key=idempotency_key,
        operation=f"caretask:complete:{task_id}",
        payload=payload,
        action=action,
    )


@router.post("/care-tasks/{task_id}/snooze")
async def snooze_care_task(
    task_id: str,
    body: CareTaskSnooze,
    user: dict = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    elder_id = await _get_managed_elder_id(user, permission="manage_reminders")
    actor_id = uuid.UUID(user["sub"])
    payload = {"task_id": task_id, **body.model_dump(mode="json")}

    async def action(_clean_key: str) -> dict[str, Any]:
        try:
            data = await svc.snooze_care_task(
                user_id=str(elder_id),
                task_id=task_id,
                minutes=body.minutes,
                expected_version=body.expected_version,
            )
        except svc.StaleCareTaskVersionError as exc:
            raise _stale_version_error(exc) from exc
        except LookupError:
            raise HTTPException(status_code=404, detail="CareTask not found")
        data["canonical"] = "CareTask"
        return data

    return await _run_idempotent(
        actor_id=actor_id,
        key=idempotency_key,
        operation=f"caretask:snooze:{task_id}",
        payload=payload,
        action=action,
    )


@router.post("/care-tasks/{task_id}/cancel")
async def cancel_care_task(
    task_id: str,
    body: CareTaskVersionedAction,
    user: dict = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    elder_id = await _get_managed_elder_id(user, permission="manage_reminders")
    actor_id = uuid.UUID(user["sub"])
    payload = {"task_id": task_id, **body.model_dump(mode="json")}

    async def action(_clean_key: str) -> dict[str, Any]:
        try:
            data = await svc.cancel_care_task(
                user_id=str(elder_id),
                task_id=task_id,
                expected_version=body.expected_version,
            )
        except svc.StaleCareTaskVersionError as exc:
            raise _stale_version_error(exc) from exc
        except LookupError:
            raise HTTPException(status_code=404, detail="CareTask not found")
        data["canonical"] = "CareTask"
        return data

    return await _run_idempotent(
        actor_id=actor_id,
        key=idempotency_key,
        operation=f"caretask:cancel:{task_id}",
        payload=payload,
        action=action,
    )


@router.post("/care-tasks/clarify")
async def clarify_care_task(
    body: CareTaskClarify,
    user: dict = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    elder_id = await _get_managed_elder_id(user, permission="manage_reminders")
    actor_id = uuid.UUID(user["sub"])
    payload = body.model_dump(mode="json")

    async def action(clean_key: str) -> dict[str, Any]:
        if body.decision == "use_existing":
            if not body.task_id:
                raise HTTPException(status_code=422, detail="task_id is required for use_existing")
            rows = await svc.list_care_tasks(user_id=str(elder_id), include_terminal=True, limit=100)
            for row in rows:
                if row["id"] == body.task_id:
                    row["clarified"] = True
                    row["canonical"] = "CareTask"
                    return row
            raise HTTPException(status_code=404, detail="CareTask not found")

        if body.proposed is None:
            raise HTTPException(status_code=422, detail="proposed task is required for create_new")
        data = await svc.create_care_task(
            user_id=str(elder_id),
            title=body.proposed.title,
            task_type=body.proposed.task_type,
            due_at=body.proposed.due_at,
            notes=body.proposed.notes,
            created_by=user.get("role", "elder"),
            link_reminder=True,
            schedule_type=body.proposed.schedule_type,
            query=body.proposed.query,
            idempotency_key=clean_key,
        )
        data["clarified"] = True
        data["canonical"] = "CareTask"
        return data

    return await _run_idempotent(
        actor_id=actor_id,
        key=idempotency_key,
        operation="caretask:clarify",
        payload=payload,
        action=action,
    )
