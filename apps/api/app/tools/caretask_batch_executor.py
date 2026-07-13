"""Preflighted execution and durable replay ledger for compound CareTask turns."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timedelta
from collections.abc import Callable
from typing import Any

from app.tools.base import ToolResult
from app.tools.caretask_batch import plan_caretask_batch
from app.tools.caretask_tool import _infer_task_type, _infer_title, parse_due_at
from app.tools import caretask_service as svc

_LEASE_SECONDS = 60
_SINGLE_OPERATION = "caretask_single"


class _SingleIdempotencyRace(RuntimeError):
    """The same single-action key was committed by a concurrent transaction."""


def _stable_request_hash(query: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", query).split()).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def single_caretask_request_payload(
    action: str,
    query: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Build the bounded semantic request whose digest owns one mutation key."""
    payload: dict[str, Any] = {
        "action": action,
        "query": " ".join(unicodedata.normalize("NFKC", query).split()).strip(),
    }
    for key in (
        "title",
        "task_type",
        "task_id",
        "minutes",
        "schedule_type",
        "due_at",
        "notes",
    ):
        value = params.get(key)
        if value is not None:
            payload[key] = value
    return payload


def _single_request_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _single_conflict_result(reason: str) -> ToolResult:
    if reason == "idempotency_conflict":
        text = "这次请求与刚才使用同一标识的操作不一致，请重新发送。"
    else:
        text = "这项照护操作仍在处理中，请稍后再试。"
    return ToolResult(
        tool_name="caretask",
        status="failed",
        display_text=text,
        data={"action": "caretask_idempotency", "reason": reason},
    )


def _single_result_from_record(record: Any, request_hash: str) -> ToolResult:
    if record.request_hash != request_hash:
        return _single_conflict_result("idempotency_conflict")
    payload = record.response_json if isinstance(record.response_json, dict) else {}
    if record.status == "completed" and payload:
        return ToolResult.model_validate(payload)
    return _single_conflict_result("idempotency_in_progress")


async def _select_single_record(
    db: Any,
    *,
    user_id: Any,
    key: str,
    for_update: bool,
) -> Any:
    from sqlalchemy import select
    from app.db.models import IdempotencyRecord

    statement = select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user_id,
        IdempotencyRecord.key == key,
        IdempotencyRecord.operation == _SINGLE_OPERATION,
    )
    if for_update:
        statement = statement.with_for_update()
    return (await db.execute(statement)).scalar_one_or_none()


async def lookup_single_caretask_result(
    *,
    user_id: str,
    idempotency_key: str,
    request_payload: dict[str, Any],
) -> ToolResult | None:
    """Read a completed replay before mutable target resolution."""
    from app.db.session import async_session

    key = idempotency_key.strip()
    request_hash = _single_request_hash(request_payload)
    async with async_session() as db:
        existing = await _select_single_record(
            db,
            user_id=svc.normalize_user_id(user_id),
            key=key,
            for_update=False,
        )
    if existing is None:
        return None
    return _single_result_from_record(existing, request_hash)


async def execute_single_caretask_mutation(
    *,
    user_id: str,
    idempotency_key: str,
    request_payload: dict[str, Any],
    mutation: dict[str, Any],
    render: Callable[[dict[str, Any]], ToolResult],
) -> ToolResult:
    """Commit one CareTask mutation and its replay result in one transaction."""
    from sqlalchemy.exc import IntegrityError
    from app.db.models import IdempotencyRecord
    from app.db.session import async_session

    key = idempotency_key.strip()
    request_hash = _single_request_hash(request_payload)
    db_user = svc.normalize_user_id(user_id)
    try:
        async with async_session() as db:
            async with db.begin():
                existing = await _select_single_record(
                    db, user_id=db_user, key=key, for_update=True
                )
                if existing is not None:
                    return _single_result_from_record(existing, request_hash)

                record = IdempotencyRecord(
                    user_id=db_user,
                    key=key,
                    operation=_SINGLE_OPERATION,
                    resource_type="care_task",
                    request_hash=request_hash,
                    response_json={},
                    status="running",
                    status_code=200,
                )
                db.add(record)
                try:
                    await db.flush()
                except IntegrityError as exc:
                    raise _SingleIdempotencyRace from exc

                now = datetime.utcnow()
                action = str(mutation["action"])
                if action == "create":
                    row = await svc.create_or_reuse_care_task_in_transaction(
                        db,
                        user_id=user_id,
                        title=str(mutation["title"]),
                        task_type=str(mutation["task_type"]),
                        due_at=mutation.get("due_at"),
                        query=str(mutation.get("query") or ""),
                        now=now,
                        reuse_task_id=mutation.get("reuse_task_id"),
                        expected_version=mutation.get("expected_version"),
                        idempotency_key=key,
                        notes=mutation.get("notes"),
                    )
                elif action in {"complete", "snooze", "cancel"}:
                    row = await svc.transition_care_task_in_transaction(
                        db,
                        user_id=user_id,
                        task_id=str(mutation["task_id"]),
                        expected_version=mutation.get("expected_version"),
                        transition=action,
                        now=now,
                        minutes=int(mutation.get("minutes") or 30),
                    )
                else:
                    raise ValueError("unsupported_single_caretask_mutation")

                result = render(dict(row))
                record.status = "completed"
                record.response_json = result.model_dump(mode="json")
                record.status_code = 200
                try:
                    record.resource_id = uuid.UUID(str(row.get("id")))
                except (TypeError, ValueError):
                    record.resource_id = None
                record.updated_at = datetime.utcnow()
                await db.flush()
            return result
    except _SingleIdempotencyRace:
        replay = await lookup_single_caretask_result(
            user_id=user_id,
            idempotency_key=key,
            request_payload=request_payload,
        )
        if replay is None:
            raise RuntimeError("single_idempotency_race_unresolved")
        return replay


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
                schedule_type = svc.infer_caretask_schedule_type(item.query)
                current_due = (
                    datetime.fromisoformat(
                        str(exact["due_at"]).replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                    if exact.get("due_at")
                    else None
                )
                changed, next_status = svc.reuse_schedule_update(
                    current_due_at=current_due,
                    current_status=str(exact["status"]),
                    current_schedule_type=exact.get("schedule_type"),
                    has_reminder=bool(exact.get("reminder_id")),
                    reminder_time_of_day=exact.get("_reminder_time_of_day"),
                    reminder_next_fire_at=exact.get("_reminder_next_fire_at"),
                    reminder_is_active=exact.get("_reminder_is_active"),
                    due_at=due,
                    schedule_type=schedule_type,
                    now=now,
                )
                if changed:
                    exact["due_at"] = due.isoformat() if due is not None else None
                    exact["status"] = next_status
                    exact["schedule_type"] = schedule_type
                    exact["version"] = exact.get("version", 1) + 1
                    exact["_reminder_time_of_day"] = due
                    exact["_reminder_next_fire_at"] = due
                    exact["_reminder_is_active"] = True
                if str(exact["id"]).startswith("planned:"):
                    action["ref_index"] = exact["_result_index"]
                    exact["_result_index"] = item.index
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
                    "status": svc.infer_initial_status(due, now),
                    "version": 1,
                    "due_at": due.isoformat() if due is not None else None,
                    "snooze_until": None,
                    "reminder_id": f"planned-reminder:{item.index}" if due else None,
                    "schedule_type": svc.infer_caretask_schedule_type(item.query),
                    "_reminder_time_of_day": due,
                    "_reminder_next_fire_at": due,
                    "_reminder_is_active": True if due else None,
                    "_result_index": item.index,
                }
            )
        elif item.action != "list":
            matches = _match_task(simulated, item.query)
            if len(matches) != 1:
                return [], "ambiguous_task_ref" if matches else "no_active_care_task"
            target = matches[0]
            action.update(task_id=target["id"], expected_version=target.get("version", 1))
            if str(target["id"]).startswith("planned:"):
                action["ref_index"] = target["_result_index"]
            if item.action == "snooze":
                action["minutes"] = item.minutes or 30
                target["status"] = "snoozed"
                target["version"] = target.get("version", 1) + 1
                snooze_until = now + timedelta(minutes=action["minutes"])
                target["due_at"] = snooze_until.isoformat()
                target["snooze_until"] = snooze_until.isoformat()
                target["_reminder_next_fire_at"] = snooze_until
                if target.get("reminder_id"):
                    target["_reminder_is_active"] = True
            elif item.action == "complete":
                target["status"] = "done"
                target["version"] = target.get("version", 1) + 1
                target["snooze_until"] = None
                target["completed_at"] = now.isoformat()
                if target.get("reminder_id"):
                    target["_reminder_is_active"] = False
            elif item.action == "cancel":
                target["status"] = "cancelled"
                target["version"] = target.get("version", 1) + 1
                target["snooze_until"] = None
                if target.get("reminder_id"):
                    target["_reminder_is_active"] = False
            target["_result_index"] = item.index
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


def _filter_list_snapshot(
    items: list[dict[str, Any]], *, scope: str, now: datetime
) -> list[dict[str, Any]]:
    if scope != "today":
        return items
    window_start, window_end, _ = svc.care_window_bounds(now)
    return [
        item
        for item in items
        if svc.in_care_window(
            status=item["status"],
            due_at=(
                datetime.fromisoformat(str(item["due_at"]).replace("Z", "+00:00")).replace(
                    tzinfo=None
                )
                if item.get("due_at")
                else None
            ),
            window_start=window_start,
            window_end=window_end,
        )
    ]


async def _lookup_replay(
    user_id: str, key: str, request_hash: str, receipts: list[dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    from sqlalchemy import select
    from app.db.models import IdempotencyRecord
    from app.db.session import async_session

    async with async_session() as db:
        existing = (
            await db.execute(
                select(IdempotencyRecord)
                .where(
                    IdempotencyRecord.user_id == svc.normalize_user_id(user_id),
                    IdempotencyRecord.key == key,
                    IdempotencyRecord.operation == "caretask_batch",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if existing is None:
            return None
        now = datetime.utcnow()
        payload, transition = _replay_snapshot(
            status=existing.status,
            existing_hash=existing.request_hash,
            payload=existing.response_json or {},
            request_hash=request_hash,
            receipts=receipts or [],
            now=now,
        )
        if transition:
            existing.status = transition
            existing.response_json = payload
            existing.updated_at = now
            await db.commit()
        return payload


async def _claim(
    user_id: str,
    key: str,
    request_hash: str,
    receipts: list[dict[str, Any]],
    *,
    plan_hash: str,
    frozen_at: str,
) -> tuple[Any, str | None, dict[str, Any] | None]:
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
        record = IdempotencyRecord(user_id=db_user, key=key, operation="caretask_batch", resource_type="care_task_batch", request_hash=request_hash, status="claimed", response_json={"status": "claimed", "owner": owner, "heartbeat_at": now.isoformat(), "frozen_at": frozen_at, "plan_hash": plan_hash, "receipts": receipts})
        db.add(record)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            replay = await _lookup_replay(user_id, key, request_hash, receipts)
            return None, None, replay
        await db.refresh(record)
        return record.id, owner, None


def _verify_ledger(record: Any, *, owner: str, request_hash: str) -> None:
    if record is None:
        raise RuntimeError("batch_ledger_not_found")
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
    async with async_session() as db:
        record = await db.get(IdempotencyRecord, record_id, with_for_update=True)
        _verify_ledger(record, owner=owner, request_hash=request_hash)
        payload = {
            **(record.response_json or {}),
            "status": status,
            "owner": owner,
            "heartbeat_at": datetime.utcnow().isoformat(),
            "receipts": receipts,
        }
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
    from app.db.models import IdempotencyRecord
    from app.db.session import async_session

    async with async_session() as db:
        ledger = await db.get(IdempotencyRecord, record_id, with_for_update=True)
        if ledger is None:
            raise RuntimeError("batch_ledger_not_found")
        _verify_ledger(ledger, owner=owner, request_hash=request_hash)
        kind = action["action"]
        if kind == "list":
            listed = await svc.snapshot_care_tasks(user_id=user_id, now=now)
            listed = _filter_list_snapshot(
                listed, scope=str(action.get("scope") or "all"), now=now
            )
            result: Any = {"count": len(listed), "titles": [item["title"] for item in listed]}
        elif kind == "create":
            result = await svc.create_or_reuse_care_task_in_transaction(
                db,
                user_id=user_id,
                title=action["title"],
                task_type=action["task_type"],
                due_at=action["due_at"],
                query=action["query"],
                now=now,
                reuse_task_id=action.get("reuse_task_id"),
                expected_version=action.get("expected_version"),
            )
        else:
            result = await svc.transition_care_task_in_transaction(
                db,
                user_id=user_id,
                task_id=action["task_id"],
                expected_version=action.get("expected_version"),
                transition=kind,
                now=now,
                minutes=action.get("minutes", 30),
            )
        receipts[action["index"]] = {
            **receipts[action["index"]],
            "status": "completed",
            "result": result,
        }
        payload = {
            **(ledger.response_json or {}),
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
    request_hash = _stable_request_hash(query)
    key = idempotency_key or request_hash
    replay = await _lookup_replay(user_id, key, request_hash)
    if replay is not None:
        return _result_from_replay(replay)

    now = datetime.utcnow()
    actions, reason = await _preflight(user_id, query, now)
    if reason:
        receipts = [{"index": 0, "action": "clarify", "status": "needs_clarification", "reason": reason}]
        record_id, owner, replay = await _claim(
            user_id,
            key,
            request_hash,
            receipts,
            plan_hash=hashlib.sha256(reason.encode()).hexdigest(),
            frozen_at=now.isoformat(),
        )
        if replay is not None:
            return _result_from_replay(replay)
        payload = await _save(
            record_id,
            "completed",
            receipts,
            owner=owner,
            request_hash=request_hash,
        )
        return ToolResult(tool_name="caretask", status="needs_clarification", display_text="为了准确处理，请再说明具体事项或时间。", data={"action": "caretask_batch", "reason": reason, **payload})
    normalized = json.dumps(actions, ensure_ascii=False, sort_keys=True, default=str)
    plan_hash = hashlib.sha256(normalized.encode()).hexdigest()
    receipts = [{"index": a["index"], "action": a["action"], "status": "planned"} for a in actions]
    record_id, owner, replay = await _claim(
        user_id,
        key,
        request_hash,
        receipts,
        plan_hash=plan_hash,
        frozen_at=now.isoformat(),
    )
    if replay is not None:
        return _result_from_replay(replay)
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


def _result_from_replay(payload: dict[str, Any]) -> ToolResult:
    ledger_status = str(payload.get("status") or "failed")
    receipts = payload.get("receipts") or []
    clarifying = any(receipt.get("status") == "needs_clarification" for receipt in receipts)
    status = "needs_clarification" if clarifying else (
        "success" if ledger_status == "completed" else ledger_status
    )
    if payload.get("reason") == "idempotency_conflict":
        status = "failed"
    display = (
        "为了准确处理，请再说明具体事项或时间。"
        if clarifying
        else _display(receipts)
    )
    return ToolResult(
        tool_name="caretask",
        status=status,
        display_text=display,
        data={"action": "caretask_batch", **payload},
    )
