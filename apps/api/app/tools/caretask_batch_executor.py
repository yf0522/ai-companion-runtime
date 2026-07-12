"""Preflighted execution and durable replay ledger for compound CareTask turns."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from app.tools.base import ToolResult
from app.tools.caretask_batch import PlannedCareAction, plan_caretask_batch
from app.tools.caretask_tool import _infer_task_type, _infer_title, parse_due_at
from app.tools import caretask_service as svc

_LEASE_SECONDS = 60


def _replay_snapshot(
    *,
    status: str,
    existing_hash: str,
    payload: dict[str, Any],
    request_hash: str,
    receipts: list[dict[str, Any]],
    now: datetime,
) -> tuple[dict[str, Any], str | None]:
    """Pure replay state machine; second value is a required persisted transition."""
    if existing_hash != request_hash:
        return {"status": "failed", "reason": "idempotency_conflict", "receipts": []}, None
    if status in {"completed", "failed", "cancelled", "interrupted"}:
        return payload, None
    heartbeat = payload.get("heartbeat_at")
    if heartbeat and datetime.fromisoformat(heartbeat) + timedelta(seconds=_LEASE_SECONDS) > now:
        return {**payload, "status": "in_progress"}, None
    current = [dict(receipt) for receipt in payload.get("receipts", receipts)]
    next_index = next((i for i, receipt in enumerate(current) if receipt["status"] == "planned"), None)
    if next_index is None and current and all(
        receipt.get("status") == "completed" for receipt in current
    ):
        return {**payload, "status": "completed", "receipts": current}, "completed"
    if next_index is not None:
        current[next_index] = {
            **current[next_index],
            "status": "failed",
            "reason": "execution_interrupted",
        }
        for index in range(next_index + 1, len(current)):
            current[index] = {
                **current[index],
                "status": "unattempted",
                "reason": "execution_interrupted",
            }
    return {**payload, "status": "interrupted", "receipts": current}, "interrupted"


def _receipt(item: PlannedCareAction) -> dict[str, Any]:
    return {"index": item.index, "action": item.action, "status": "planned", "query": item.query}


def _match_task(tasks: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    hint = svc.extract_resolve_hint(None, query)
    if re.search(r"(?:把)?(?:吃药|服药|用药)提醒(?:取消|删掉|删除)?", query) or not hint or svc.is_generic_med_hint(hint):
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
        if item.action == "list":
            action["scope"] = "today" if re.search(r"今天|今日", item.query) else "all"
        if item.action == "create":
            due = parse_due_at(item.query, now=now)
            if "提醒" in item.query and due is None:
                return [], "reminder_time_required"
            action.update(title=_infer_title(item.query, _infer_task_type(item.query)), task_type=_infer_task_type(item.query), due_at=due)
            fingerprint = svc.identity_key(action["title"], action["task_type"])
            exact = next(
                (
                    task
                    for task in simulated
                    if task.get("status") in svc.ACTIVE_STATUSES
                    and svc.identity_key(task["title"], task.get("task_type") or action["task_type"])
                    == fingerprint
                ),
                None,
            )
            if exact is not None:
                action.update(
                    reuse_task_id=exact["id"],
                    expected_version=exact.get("version", 1),
                )
                if str(exact["id"]).startswith("planned:"):
                    action["ref_index"] = int(str(exact["id"]).split(":", 1)[1])
                actions.append(action)
                continue
            near = [
                task
                for task in simulated
                if task.get("status") in svc.ACTIVE_STATUSES
                and (task.get("task_type") or action["task_type"]) == action["task_type"]
                and svc._token_overlap(action["title"], task["title"]) >= 0.55
            ]
            if near:
                return [], "near_duplicate_care_task"
            simulated.append(
                {
                    "id": f"planned:{item.index}",
                    "title": action["title"],
                    "task_type": action["task_type"],
                    "status": "pending",
                    "version": 1,
                }
            )
        elif item.action != "list":
            matches = _match_task(simulated, item.query)
            if len(matches) != 1:
                return [], "ambiguous_task_ref" if matches else "no_active_care_task"
            target = matches[0]
            action.update(task_id=target["id"], expected_version=target.get("version", 1))
            if str(target["id"]).startswith("planned:"):
                action["ref_index"] = int(str(target["id"]).split(":", 1)[1])
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
    lines = []
    for receipt in receipts:
        result = receipt.get("result") or {}
        detail = ""
        if receipt.get("action") == "list" and result.get("titles"):
            detail = "（" + "、".join(result["titles"]) + "）"
        elif result.get("title"):
            detail = f"（{result['title']}）"
        lines.append(
            f"{receipt['index'] + 1}. {labels.get(receipt['action'], receipt['action'])}"
            f"{detail}：{states.get(receipt['status'], receipt['status'])}"
        )
    return "\n".join(lines)


async def _claim(user_id: str, key: str, request_hash: str, receipts: list[dict[str, Any]]) -> tuple[Any, str | None, dict[str, Any] | None]:
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from app.db.models import IdempotencyRecord
    from app.db.session import async_session

    db_user = svc.normalize_user_id(user_id)
    async with async_session() as db:
        existing = (await db.execute(select(IdempotencyRecord).where(IdempotencyRecord.user_id == db_user, IdempotencyRecord.key == key, IdempotencyRecord.operation == "caretask_batch").with_for_update())).scalar_one_or_none()
        now = datetime.utcnow()
        if existing:
            payload = existing.response_json or {}
            payload, transition = _replay_snapshot(
                status=existing.status,
                existing_hash=existing.request_hash,
                payload=payload,
                request_hash=request_hash,
                receipts=receipts,
                now=now,
            )
            if transition:
                existing.status = transition
                existing.response_json = payload
                existing.updated_at = now
                await db.commit()
            return None, None, payload
        owner = uuid.uuid4().hex
        record = IdempotencyRecord(user_id=db_user, key=key, operation="caretask_batch", resource_type="care_task_batch", request_hash=request_hash, status="claimed", response_json={"status": "claimed", "owner": owner, "heartbeat_at": now.isoformat(), "receipts": receipts})
        db.add(record)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return await _claim(user_id, key, request_hash, receipts)
        await db.refresh(record)
        return record.id, owner, None


def _verify_ledger(record: Any, *, owner: str, request_hash: str) -> None:
    payload = record.response_json or {}
    if record.request_hash != request_hash:
        raise RuntimeError("idempotency_conflict")
    if payload.get("owner") != owner:
        raise RuntimeError("batch_owner_mismatch")
    if record.status not in {"claimed", "running"}:
        raise RuntimeError("batch_ledger_not_active")


async def _save(record_id: Any, status: str, receipts: list[dict[str, Any]], *, owner: str, request_hash: str) -> dict[str, Any]:
    from app.db.models import IdempotencyRecord
    from app.db.session import async_session
    payload = {"status": status, "owner": owner, "heartbeat_at": datetime.utcnow().isoformat(), "receipts": receipts}
    async with async_session() as db:
        record = await db.get(IdempotencyRecord, record_id, with_for_update=True)
        _verify_ledger(record, owner=owner, request_hash=request_hash)
        record.status = status
        record.response_json = payload
        record.updated_at = datetime.utcnow()
        await db.commit()
    return payload


async def _apply_action_transaction(
    *,
    record_id: Any,
    user_id: str,
    action: dict[str, Any],
    receipts: list[dict[str, Any]],
    now: datetime,
    owner: str,
    request_hash: str,
) -> dict[str, Any]:
    """Commit one domain mutation and its receipt under the same transaction."""
    from app.db.models import CareTask, IdempotencyRecord, Reminder
    from app.db.session import async_session

    async with async_session() as db:
        ledger = await db.get(IdempotencyRecord, record_id, with_for_update=True)
        if ledger is None:
            raise RuntimeError("batch_ledger_not_found")
        _verify_ledger(ledger, owner=owner, request_hash=request_hash)
        kind = action["action"]
        db_user = svc.normalize_user_id(user_id)
        if kind == "list":
            listed = await svc.snapshot_care_tasks(user_id=user_id, now=now)
            if action.get("scope") == "today":
                window_start, window_end, _ = svc.care_window_bounds(now)
                listed = [
                    item
                    for item in listed
                    if svc.in_care_window(
                        status=item["status"],
                        due_at=(
                            datetime.fromisoformat(str(item["due_at"]).replace("Z", "+00:00"))
                            .replace(tzinfo=None)
                            if item.get("due_at")
                            else None
                        ),
                        window_start=window_start,
                        window_end=window_end,
                    )
                ]
            result: Any = {"count": len(listed), "titles": [item["title"] for item in listed]}
        elif kind == "create":
            reminder_id = None
            schedule_type = "daily" if re.search(r"每天|每日", action["query"]) else "once"
            if action.get("reuse_task_id"):
                row = await svc._get_versioned_task_for_update(
                    db,
                    db_user,
                    action["reuse_task_id"],
                    action["expected_version"],
                )
                reminder = await db.get(Reminder, row.reminder_id) if row.reminder_id else None
                if action["due_at"] is not None:
                    row.due_at = action["due_at"]
                    row.status = svc.infer_initial_status(action["due_at"], now)
                    if reminder is None:
                        reminder = Reminder(
                            user_id=db_user,
                            title=row.title,
                            description=f"caretask:{row.task_type}",
                            schedule_type=schedule_type,
                            time_of_day=action["due_at"],
                            next_fire_at=action["due_at"],
                            is_active=True,
                            created_by="chat",
                        )
                        db.add(reminder)
                        await db.flush()
                        row.reminder_id = reminder.id
                    else:
                        reminder.schedule_type = schedule_type
                        reminder.time_of_day = action["due_at"]
                        reminder.next_fire_at = action["due_at"]
                        reminder.is_active = True
                    row.version = (row.version or 1) + 1
                await db.flush()
                result = svc.task_to_dict(row, schedule_type=schedule_type)
                result["_action"] = "caretask_reuse"
            elif action["due_at"] is not None:
                reminder = Reminder(
                    user_id=db_user,
                    title=action["title"],
                    description=f"caretask:{action['task_type']}",
                    schedule_type=schedule_type,
                    time_of_day=action["due_at"],
                    next_fire_at=action["due_at"],
                    is_active=True,
                    created_by="chat",
                )
                db.add(reminder)
                await db.flush()
                reminder_id = reminder.id
            if not action.get("reuse_task_id"):
                row = CareTask(
                    user_id=db_user,
                    title=action["title"],
                    task_type=action["task_type"],
                    status=svc.infer_initial_status(action["due_at"], now),
                    due_at=action["due_at"],
                    reminder_id=reminder_id,
                    created_by="chat",
                )
                db.add(row)
                await db.flush()
                result = svc.task_to_dict(row, schedule_type=schedule_type)
        else:
            row = await svc._get_versioned_task_for_update(
                db, db_user, action["task_id"], action["expected_version"]
            )
            reminder = await db.get(Reminder, row.reminder_id) if row.reminder_id else None
            if kind == "snooze":
                svc.assert_transition(row.status, "snoozed")
                row.status = "snoozed"
                row.snooze_until = now + timedelta(minutes=action["minutes"])
                row.due_at = row.snooze_until
                if reminder is not None:
                    reminder.next_fire_at = row.snooze_until
                    reminder.is_active = True
            elif kind == "complete":
                svc.assert_transition(row.status, "done")
                row.status = "done"
                row.completed_at = now
                row.snooze_until = None
                if reminder is not None:
                    reminder.is_active = False
            else:
                svc.assert_transition(row.status, "cancelled")
                row.status = "cancelled"
                row.snooze_until = None
                if reminder is not None:
                    reminder.is_active = False
            row.version = (row.version or 1) + 1
            row.updated_at = now
            await db.flush()
            result = svc.task_to_dict(
                row, schedule_type=reminder.schedule_type if reminder is not None else None
            )
        receipts[action["index"]] = {
            **receipts[action["index"]],
            "status": "completed",
            "result": result,
        }
        payload = {
            "status": "running",
            "owner": owner,
            "heartbeat_at": datetime.utcnow().isoformat(),
            "receipts": receipts,
        }
        ledger.status = "running"
        ledger.response_json = payload
        ledger.updated_at = datetime.utcnow()
        await db.commit()
        return result


async def execute_caretask_batch(*, user_id: str, query: str, idempotency_key: str, cancel_event: asyncio.Event | None = None) -> ToolResult:
    if cancel_event and cancel_event.is_set():
        return ToolResult(
            tool_name="caretask",
            status="cancelled",
            display_text="已取消，本次没有更改照护事项。",
            data={"action": "caretask_batch", "status": "cancelled", "receipts": []},
        )
    now = datetime.utcnow()
    actions, reason = await _preflight(user_id, query, now)
    if reason:
        request_hash = hashlib.sha256(query.strip().encode()).hexdigest()
        receipts = [{"index": 0, "action": "clarify", "status": "needs_clarification", "reason": reason}]
        record_id, owner, replay = await _claim(
            user_id, idempotency_key or request_hash, request_hash, receipts
        )
        payload = replay or await _save(
            record_id,
            "completed",
            receipts,
            owner=owner,
            request_hash=request_hash,
        )
        return ToolResult(tool_name="caretask", status="needs_clarification", display_text="为了准确处理，请再说明具体事项或时间。", data={"action": "caretask_batch", "reason": reason, **payload})
    normalized = json.dumps(actions, ensure_ascii=False, sort_keys=True, default=str)
    request_hash = hashlib.sha256(normalized.encode()).hexdigest()
    receipts = [{"index": a["index"], "action": a["action"], "status": "planned"} for a in actions]
    record_id, owner, replay = await _claim(user_id, idempotency_key or request_hash, request_hash, receipts)
    if replay is not None:
        status = replay.get("status", "failed")
        return ToolResult(tool_name="caretask", status="success" if status == "completed" else status, display_text=_display(replay.get("receipts", [])), data={"action": "caretask_batch", **replay})
    if cancel_event and cancel_event.is_set():
        receipts = [{**r, "status": "unattempted", "reason": "cancelled"} for r in receipts]
        payload = await _save(record_id, "cancelled", receipts, owner=owner, request_hash=request_hash)
        return ToolResult(tool_name="caretask", status="cancelled", display_text=_display(receipts), data={"action": "caretask_batch", **payload})
    for index, action in enumerate(actions):
        try:
            if cancel_event and cancel_event.is_set():
                for later in range(index, len(receipts)):
                    receipts[later] = {**receipts[later], "status": "unattempted", "reason": "cancelled"}
                payload = await _save(record_id, "cancelled", receipts, owner=owner, request_hash=request_hash)
                return ToolResult(tool_name="caretask", status="cancelled", display_text=_display(receipts), data={"action": "caretask_batch", **payload})
            if "ref_index" in action:
                created = receipts[action["ref_index"]].get("result") or {}
                resolved_key = "reuse_task_id" if action["action"] == "create" else "task_id"
                action = {**action, resolved_key: created.get("id"), "expected_version": created.get("version", 1)}
            await _apply_action_transaction(
                record_id=record_id,
                user_id=user_id,
                action=action,
                receipts=receipts,
                now=now,
                owner=owner,
                request_hash=request_hash,
            )
        except Exception as exc:
            receipts[index] = {**receipts[index], "status": "failed", "reason": type(exc).__name__}
            for later in range(index + 1, len(receipts)):
                receipts[later] = {**receipts[later], "status": "unattempted", "reason": "prior_action_failed"}
            payload = await _save(record_id, "failed", receipts, owner=owner, request_hash=request_hash)
            return ToolResult(tool_name="caretask", status="failed", display_text=_display(receipts), data={"action": "caretask_batch", **payload})
    payload = await _save(record_id, "completed", receipts, owner=owner, request_hash=request_hash)
    return ToolResult(tool_name="caretask", status="success", display_text=_display(receipts), data={"action": "caretask_batch", **payload})
