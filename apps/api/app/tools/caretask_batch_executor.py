"""Preflighted execution and durable replay ledger for compound CareTask turns."""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from app.tools.base import ToolResult
from app.tools.caretask_batch import PlannedCareAction, plan_caretask_batch
from app.tools.caretask_tool import _infer_task_type, _infer_title, parse_due_at
from app.tools import caretask_service as svc

_LEASE_SECONDS = 60


def _receipt(item: PlannedCareAction) -> dict[str, Any]:
    return {"index": item.index, "action": item.action, "status": "planned", "query": item.query}


def _match_task(tasks: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    hint = svc.extract_resolve_hint(None, query)
    if not hint or svc.is_generic_med_hint(hint):
        return [task for task in tasks if task.get("task_type") == "medication"]
    normalized = svc.normalize_title(hint)
    return [task for task in tasks if normalized in svc.normalize_title(task["title"]) or svc.normalize_title(task["title"]) in normalized]


async def _preflight(user_id: str, query: str, now: datetime) -> tuple[list[dict[str, Any]], str | None]:
    plan = plan_caretask_batch(query, now=now)
    if plan.status != "planned":
        return [], plan.reason
    tasks = await svc.snapshot_care_tasks(user_id=user_id, now=now)
    actions: list[dict[str, Any]] = []
    simulated = [dict(task) for task in tasks]
    for item in plan.actions:
        action = {"index": item.index, "action": item.action, "query": item.query}
        if item.action == "create":
            due = parse_due_at(item.query, now=now)
            if "提醒" in item.query and due is None:
                return [], "reminder_time_required"
            action.update(title=_infer_title(item.query, _infer_task_type(item.query)), task_type=_infer_task_type(item.query), due_at=due)
        elif item.action != "list":
            matches = _match_task(simulated, item.query)
            if len(matches) != 1:
                return [], "ambiguous_task_ref" if matches else "no_active_care_task"
            target = matches[0]
            action.update(task_id=target["id"], expected_version=target.get("version", 1))
            if item.action == "snooze":
                action["minutes"] = item.minutes or 30
                target["status"] = "snoozed"
                target["version"] = target.get("version", 1) + 1
            elif item.action == "complete":
                target["status"] = "done"
                target["version"] = target.get("version", 1) + 1
            elif item.action == "cancel":
                target["status"] = "cancelled"
                target["version"] = target.get("version", 1) + 1
            simulated = [task for task in simulated if task.get("status") in svc.ACTIVE_STATUSES]
        actions.append(action)
    return actions, None


def _display(receipts: list[dict[str, Any]]) -> str:
    labels = {"list": "查看", "create": "记下", "snooze": "推迟", "complete": "完成", "cancel": "取消"}
    states = {"completed": "已完成", "failed": "未完成", "unattempted": "未执行", "planned": "待执行"}
    return "\n".join(f"{r['index'] + 1}. {labels.get(r['action'], r['action'])}：{states.get(r['status'], r['status'])}" for r in receipts)


async def _claim(user_id: str, key: str, request_hash: str, receipts: list[dict[str, Any]]) -> tuple[Any, dict[str, Any] | None]:
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from app.db.models import IdempotencyRecord
    from app.db.session import async_session

    db_user = svc.normalize_user_id(user_id)
    async with async_session() as db:
        existing = (await db.execute(select(IdempotencyRecord).where(IdempotencyRecord.user_id == db_user, IdempotencyRecord.key == key, IdempotencyRecord.operation == "caretask_batch").with_for_update())).scalar_one_or_none()
        now = datetime.utcnow()
        if existing:
            if existing.request_hash != request_hash:
                return None, {"status": "failed", "reason": "idempotency_conflict", "receipts": []}
            payload = existing.response_json or {}
            if existing.status in {"completed", "failed", "cancelled", "interrupted"}:
                return None, payload
            heartbeat = payload.get("heartbeat_at")
            if heartbeat and datetime.fromisoformat(heartbeat) + timedelta(seconds=_LEASE_SECONDS) > now:
                return None, {**payload, "status": "in_progress"}
            current = payload.get("receipts", receipts)
            next_index = next((i for i, r in enumerate(current) if r["status"] == "planned"), None)
            if next_index is not None:
                current[next_index] = {**current[next_index], "status": "failed", "reason": "execution_interrupted"}
                for i in range(next_index + 1, len(current)):
                    current[i] = {**current[i], "status": "unattempted", "reason": "execution_interrupted"}
            payload = {**payload, "status": "interrupted", "receipts": current}
            existing.status = "interrupted"
            existing.response_json = payload
            existing.updated_at = now
            await db.commit()
            return None, payload
        record = IdempotencyRecord(user_id=db_user, key=key, operation="caretask_batch", resource_type="care_task_batch", request_hash=request_hash, status="claimed", response_json={"status": "claimed", "owner": uuid.uuid4().hex, "heartbeat_at": now.isoformat(), "receipts": receipts})
        db.add(record)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return await _claim(user_id, key, request_hash, receipts)
        await db.refresh(record)
        return record.id, None


async def _save(record_id: Any, status: str, receipts: list[dict[str, Any]]) -> dict[str, Any]:
    from app.db.models import IdempotencyRecord
    from app.db.session import async_session
    payload = {"status": status, "heartbeat_at": datetime.utcnow().isoformat(), "receipts": receipts}
    async with async_session() as db:
        record = await db.get(IdempotencyRecord, record_id, with_for_update=True)
        record.status = status
        record.response_json = payload
        record.updated_at = datetime.utcnow()
        await db.commit()
    return payload


async def execute_caretask_batch(*, user_id: str, query: str, idempotency_key: str, cancel_event: asyncio.Event | None = None) -> ToolResult:
    now = datetime.utcnow()
    actions, reason = await _preflight(user_id, query, now)
    if reason:
        return ToolResult(tool_name="caretask", status="needs_clarification", display_text="为了准确处理，请再说明具体事项或时间。", data={"action": "caretask_batch", "reason": reason, "receipts": []})
    normalized = json.dumps(actions, ensure_ascii=False, sort_keys=True, default=str)
    request_hash = hashlib.sha256(normalized.encode()).hexdigest()
    receipts = [{"index": a["index"], "action": a["action"], "status": "planned"} for a in actions]
    record_id, replay = await _claim(user_id, idempotency_key or request_hash, request_hash, receipts)
    if replay is not None:
        status = replay.get("status", "failed")
        return ToolResult(tool_name="caretask", status="success" if status == "completed" else status, display_text=_display(replay.get("receipts", [])), data={"action": "caretask_batch", **replay})
    if cancel_event and cancel_event.is_set():
        receipts = [{**r, "status": "unattempted", "reason": "cancelled"} for r in receipts]
        payload = await _save(record_id, "cancelled", receipts)
        return ToolResult(tool_name="caretask", status="cancelled", display_text=_display(receipts), data={"action": "caretask_batch", **payload})
    for index, action in enumerate(actions):
        try:
            if cancel_event and cancel_event.is_set():
                for later in range(index, len(receipts)):
                    receipts[later] = {**receipts[later], "status": "unattempted", "reason": "cancelled"}
                payload = await _save(record_id, "cancelled", receipts)
                return ToolResult(tool_name="caretask", status="cancelled", display_text=_display(receipts), data={"action": "caretask_batch", **payload})
            if action["action"] == "list":
                result = await svc.snapshot_care_tasks(user_id=user_id, now=now)
            elif action["action"] == "create":
                result = await svc.create_care_task(user_id=user_id, title=action["title"], task_type=action["task_type"], due_at=action["due_at"], created_by="chat", link_reminder=action["due_at"] is not None, query=action["query"])
            elif action["action"] == "snooze":
                result = await svc.snooze_care_task(user_id=user_id, task_id=action["task_id"], minutes=action["minutes"], expected_version=action["expected_version"])
            elif action["action"] == "complete":
                result = await svc.complete_care_task(user_id=user_id, task_id=action["task_id"], expected_version=action["expected_version"])
            else:
                result = await svc.cancel_care_task(user_id=user_id, task_id=action["task_id"], expected_version=action["expected_version"])
            receipts[index] = {**receipts[index], "status": "completed", "result": result}
            await _save(record_id, "running", receipts)
        except Exception as exc:
            receipts[index] = {**receipts[index], "status": "failed", "reason": type(exc).__name__}
            for later in range(index + 1, len(receipts)):
                receipts[later] = {**receipts[later], "status": "unattempted", "reason": "prior_action_failed"}
            payload = await _save(record_id, "failed", receipts)
            return ToolResult(tool_name="caretask", status="failed", display_text=_display(receipts), data={"action": "caretask_batch", **payload})
    payload = await _save(record_id, "completed", receipts)
    return ToolResult(tool_name="caretask", status="success", display_text=_display(receipts), data={"action": "caretask_batch", **payload})
