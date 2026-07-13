"""CareTask ToolBase — create/list/complete/snooze (+ cancel/missed)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.tools.base import ToolBase, ToolResult
from app.tools import caretask_service as svc

logger = logging.getLogger(__name__)

_ACTION_ALIASES = {
    "create": "create",
    "add": "create",
    "list": "list",
    "show": "list",
    "complete": "complete",
    "done": "complete",
    "finish": "complete",
    "snooze": "snooze",
    "delay": "snooze",
    "cancel": "cancel",
    "missed": "missed",
}
_MODEL_SEMANTIC_FIELDS = (
    "task_id",
    "title",
    "task_type",
    "due_at",
    "minutes",
    "notes",
    "schedule_type",
)


def parse_due_at(text: str, *, now: datetime | None = None) -> datetime | None:
    """Parse an Asia/Shanghai wall clock into the naive-UTC storage contract."""
    try:
        from app.tools.reminder_tool import parse_time_from_text

        t = parse_time_from_text(text)
        if t is None:
            return None
        now_utc = now or datetime.utcnow()
        shanghai = ZoneInfo("Asia/Shanghai")
        local_now = now_utc.replace(tzinfo=timezone.utc).astimezone(shanghai)
        local_due = local_now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        explicit_today = "今天" in text
        if "后天" in text:
            local_due += timedelta(days=2)
        elif "明天" in text:
            local_due += timedelta(days=1)
        elif local_due <= local_now:
            if explicit_today:
                return None
            local_due += timedelta(days=1)
        return local_due.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def format_caretask_time(value: Any, *, now: datetime | None = None) -> str:
    """Format stored UTC timestamps for elders while leaving payload ISO intact."""
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        shanghai = ZoneInfo("Asia/Shanghai")
        local = parsed.astimezone(shanghai)
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        local_now = reference.astimezone(shanghai)

        hour = local.hour
        if 5 <= hour < 8:
            period = "清晨"
        elif 8 <= hour < 12:
            period = "上午"
        elif 12 <= hour < 14:
            period = "中午"
        elif 14 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 23:
            period = "晚上"
        else:
            period = "夜里"

        day_delta = (local.date() - local_now.date()).days
        relative_days = {0: "今天", 1: "明天", 2: "后天"}
        if day_delta in relative_days:
            day_label = relative_days[day_delta]
        else:
            day_label = f"{local.year}年{local.month}月{local.day}日"
        return f"{day_label}{period} {local:%H:%M}"
    except (TypeError, ValueError):
        return ""


def _promises_reminder(text: str) -> bool:
    return bool(re.search(r"提醒(?:我)?|闹钟|到点|叫我", text))


def _infer_task_type(text: str) -> str:
    if re.search(r"复诊|预约|看病|医院|门诊", text):
        return "appointment"
    if re.search(r"药|服用|服药|打针|胰岛素", text):
        return "medication"
    return "other"


def _infer_title(text: str, task_type: str) -> str:
    m = re.search(
        r"(?:提醒我|记得|帮我记一下|帮我记下|帮我|记一下)?(.{2,24}?)(?:吧|啊|哦)?$",
        text.strip(),
    )
    raw = (m.group(1) if m else text).strip()
    # Strip schedule fragments so stored titles match identity normalize.
    raw = re.sub(
        r"(?:每天|每日|每周|明天|今天|后天)?"
        r"(?:早上|上午|中午|下午|傍晚|晚上|夜里|凌晨)?"
        r"(?:\d{1,2}\s*[点时:](?:\d{1,2}\s*分?)?|"
        r"[零一二三四五六七八九十两]+\s*[点时](?:\s*[零一二三四五六七八九十]+\s*分?)?)?",
        "",
        raw,
    )
    raw = re.sub(r"^(每天|明天|今天|晚上|早上|下午|中午)", "", raw).strip()
    raw = re.sub(r"^(记一下|记下|提醒我|记得)", "", raw).strip()
    if len(raw) < 2:
        return "吃药" if task_type == "medication" else "复诊"
    return raw[:80]


def _infer_action_from_query(query: str) -> str:
    from app.tools.caretask_batch import is_explicit_scheduled_create

    # Read-only language wins over mutation words. This prevents phrases such
    # as "今天完成了哪些任务" from being interpreted as a completion command.
    if re.search(
        r"有哪些|有什么|列出|查看|看看|查一下|我的.*任务|待办|还没吃|"
        r"今日(?:事项|任务)|今天.*(?:任务|事项|安排)|今天需要做什么|需要做什么",
        query,
    ):
        return "list"
    if re.search(r"晚点再|等会儿再|推迟|再提醒|分钟后再", query):
        return "snooze"
    if re.search(r"吃完了|吃过了|已经吃|完成了|打卡|确认.*吃", query):
        return "complete"
    if re.search(r"取消|不要了|删掉", query):
        return "cancel"
    if re.search(
        r"提醒我|帮我记(?:一下|下)|记一下|记下|新增|添加|新建|创建|建立|设置|安排",
        query,
    ) or is_explicit_scheduled_create(query):
        return "create"
    # Ambiguous care-domain utterances are read-only by default. A write must
    # be grounded in an explicit user mutation cue.
    return "list"


def _format_candidates(candidates: list[dict[str, Any]]) -> str:
    """Elder-facing candidate list — titles only, no status/id jargon."""
    lines = []
    for i, t in enumerate(candidates[:8], start=1):
        rendered = format_caretask_time(t.get("due_at"))
        due = f"（{rendered}）" if rendered else ""
        lines.append(f"（{i}）{t['title']}{due}")
    return "\n".join(lines)


def _candidate_payload(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": c["id"],
            "title": c["title"],
            "status": c.get("status"),
            "due_at": c.get("due_at"),
            "task_type": c.get("task_type"),
        }
        for c in candidates
    ]


def _reuse_display(title: str, *, schedule_updated: bool) -> str:
    """Natural Chinese for CareTask reuse — no pending/status jargon."""
    label = title.strip()
    # Avoid 「吃吃降压药」 when title already starts with 吃.
    if "药" in label and not label.startswith("吃"):
        label = f"吃{label}"
    if schedule_updated:
        return f"您已经有{label}的提醒了，我帮您更新了提醒时间。"
    return f"您已经记过{label}这件事了，我会继续为您保留。"


def _create_result(row: dict[str, Any], query: str) -> ToolResult:
    row = dict(row)
    action = row.pop("_action", "caretask_create")
    schedule_updated = bool(row.pop("_schedule_updated", False))
    schedule_type = row.get("schedule_type")
    if action == "caretask_reuse":
        device_action = (
            "caretask_schedule_updated" if schedule_updated else "caretask_reuse"
        )
        return ToolResult(
            tool_name="caretask",
            status="success",
            display_text=_reuse_display(
                row["title"], schedule_updated=schedule_updated
            ),
            data={
                "action": device_action,
                "task": row,
                "schedule_updated": schedule_updated,
                "schedule_type": schedule_type,
                "query": query,
            },
        )
    if action == "caretask_clarify_create":
        candidates = row.get("candidates") or []
        return ToolResult(
            tool_name="caretask",
            status="needs_clarification",
            display_text=(
                "已有相似照护任务，请点选要改时间的那一项，或告诉我新建：\n"
                + _format_candidates(candidates)
            ),
            data={
                "action": "caretask_clarify_create",
                "clarify_verb": "确认",
                "candidates": _candidate_payload(candidates),
                "proposed": row.get("proposed"),
            },
        )
    rendered_due = format_caretask_time(row.get("due_at"))
    due_text = f"（{rendered_due}）" if rendered_due else ""
    return ToolResult(
        tool_name="caretask",
        status="success",
        display_text=f"已为您记下：{row['title']}{due_text}",
        data={
            "action": "caretask_create",
            "task": row,
            "schedule_type": schedule_type,
            "query": query,
        },
    )


def _none_resolve_display(verb_cn: str, resolved: Any) -> str:
    hint = getattr(resolved, "hint", None) or ""
    if getattr(resolved, "already_done", False) and hint:
        return f"「{hint}」的提醒已经完成过了，目前没有待完成的。"
    if hint and not svc.is_generic_med_hint(hint):
        return f"没有待{verb_cn}的{hint}提醒"
    return f"没有可{verb_cn}的照护任务"


class CareTaskTool(ToolBase):
    name = "caretask"
    description = (
        "Manage eldercare CareTasks (medication/appointment): "
        "create, list, complete, snooze, cancel. Reminder is scheduling projection. "
        "action=list defaults to today's local care-window tasks (due today, active undated, "
        "due/snoozed/missed) with status/title/task_type/due_at/notes for LLM dump — "
        "use this instead of a separate today_brief tool. Pass scope=all for full list."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "complete", "snooze", "cancel", "missed"],
                "description": "CareTask operation",
            },
            "title": {"type": "string", "description": "Task title (create)"},
            "task_type": {
                "type": "string",
                "enum": ["medication", "appointment", "other"],
            },
            "task_id": {"type": "string", "description": "CareTask UUID"},
            "due_at": {
                "type": "string",
                "description": "ISO due datetime (optional)",
            },
            "minutes": {"type": "integer", "description": "Snooze minutes"},
            "notes": {"type": "string"},
            "scope": {
                "type": "string",
                "enum": ["today", "all"],
                "description": "list only: today=care-window (default), all=unfiltered",
            },
            "query": {"type": "string", "description": "Natural language fallback"},
        },
        "required": ["action"],
    }

    async def execute(self, params: dict) -> ToolResult:
        params = dict(params)
        action = str(params.get("action") or "").strip().lower()
        query = str(params.get("query") or "")
        if query:
            for key in _MODEL_SEMANTIC_FIELDS:
                params.pop(key, None)
        from app.tools.caretask_batch import classify_caretask_speech_act

        speech_act = classify_caretask_speech_act(query) if query else None
        if (
            action != "batch"
            and speech_act
            and speech_act.action not in {None, "list"}
            and not speech_act.authorized
        ):
            return ToolResult(
                tool_name=self.name,
                status="needs_clarification",
                display_text="我听到了照护事项的说法，但还不能确认您要我执行。请直接告诉我要新增、完成、推迟还是取消。",
                data={
                    "action": "caretask_clarification",
                    "reason": speech_act.reason or "mutation_not_authorized",
                },
            )
        if not action or action == "auto":
            action = speech_act.action if speech_act and speech_act.authorized else _infer_action_from_query(query)
        elif (
            action
            in {
                "create",
                "add",
                "complete",
                "done",
                "finish",
                "snooze",
                "delay",
                "cancel",
                "missed",
            }
            and query
            and (not speech_act or speech_act.action == "list" or not speech_act.authorized)
        ):
            # The user's read-only wording is authoritative. A model-supplied
            # mutation label cannot turn a question or ambiguous care phrase
            # into a persisted change.
            action = "list"
        elif speech_act and speech_act.authorized:
            action = speech_act.action
        action = _ACTION_ALIASES.get(action, action)

        user_id = params.get("user_id")
        if not user_id:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="无法处理照护任务：缺少用户信息",
                data={"reason": "missing_user", "action": action},
            )

        try:
            if action in {"create", "complete", "snooze", "cancel"}:
                idempotency_key = str(params.get("idempotency_key") or "").strip()
                if idempotency_key:
                    from app.tools.caretask_batch_executor import (
                        lookup_single_caretask_result,
                        single_caretask_request_payload,
                    )

                    request_payload = single_caretask_request_payload(
                        action, query, params
                    )
                    replay = await lookup_single_caretask_result(
                        user_id=str(user_id),
                        idempotency_key=idempotency_key,
                        request_payload=request_payload,
                    )
                    if replay is not None:
                        return replay
                    params = {
                        **params,
                        "_single_idempotency_request": request_payload,
                    }
            if action == "create":
                return await self._create(params, user_id, query)
            if action == "list":
                return await self._list(params, user_id)
            if action == "complete":
                return await self._complete(params, user_id, query)
            if action == "snooze":
                return await self._snooze(params, user_id, query)
            if action == "cancel":
                return await self._cancel(params, user_id, query)
            if action == "missed":
                return await self._missed(params, user_id)
            if action == "batch":
                return await self._batch(params, user_id, query)
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text=f"不支持的照护任务操作：{action}",
                data={"reason": "unknown_action", "action": action},
            )
        except svc.CareTaskTransitionError as e:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="当前状态不能执行该操作",
                data={
                    "reason": "invalid_transition",
                    "error_class": type(e).__name__,
                    "action": action,
                },
            )
        except LookupError as e:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="没有找到对应的照护任务",
                data={
                    "reason": "not_found",
                    "error_class": type(e).__name__,
                    "action": action,
                },
            )
        except Exception as e:
            logger.error(
                "CareTask tool failed error_class=%s code=caretask_execution_failed",
                type(e).__name__,
            )
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="照护任务处理失败，请稍后重试",
                data={
                    "reason": "exception",
                    "error_class": type(e).__name__,
                    "error_code": "caretask_execution_failed",
                    "action": action,
                },
            )

    async def _create(self, params: dict, user_id: str, query: str) -> ToolResult:
        title = str(params.get("title") or "").strip()
        task_type = str(params.get("task_type") or _infer_task_type(query or title))
        if not title:
            title = _infer_title(query, task_type)
        # Model-provided timestamps are untrusted semantic arguments. A CareTask
        # is scheduled only when the user's own utterance contains a parseable time.
        due_at = parse_due_at(query) if query else None
        schedule_type = (
            svc.infer_caretask_schedule_type(query or title)
            if query
            else params.get("schedule_type")
        )
        if query and _promises_reminder(query) and due_at is None:
            return ToolResult(
                tool_name=self.name,
                status="needs_clarification",
                display_text="您希望我在什么具体时间提醒您？",
                data={"action": "caretask_create", "reason": "reminder_time_required"},
            )

        request_payload = params.get("_single_idempotency_request")
        if isinstance(request_payload, dict):
            from app.tools.caretask_batch_executor import (
                execute_single_caretask_mutation,
            )

            now = datetime.utcnow()
            tasks = await svc.snapshot_care_tasks(user_id=str(user_id), now=now)
            fingerprint = svc.identity_key(title, task_type)
            existing = next(
                (
                    task
                    for task in tasks
                    if task.get("status") in svc.ACTIVE_STATUSES
                    and svc.identity_key(
                        task["title"], task.get("task_type") or task_type
                    )
                    == fingerprint
                ),
                None,
            )
            if existing is None:
                near = [
                    task
                    for task in tasks
                    if task.get("status") in svc.ACTIVE_STATUSES
                    and (task.get("task_type") or task_type) == task_type
                    and svc._token_overlap(title, task["title"]) >= 0.55
                ]
                if near:
                    return _create_result(
                        {
                            "_action": "caretask_clarify_create",
                            "candidates": near,
                            "proposed": {
                                "title": title,
                                "task_type": task_type,
                                "due_at": due_at.isoformat() if due_at else None,
                                "schedule_type": schedule_type,
                            },
                        },
                        query,
                    )
            mutation = {
                "action": "create",
                "title": title,
                "task_type": task_type,
                "due_at": due_at,
                "query": query or title,
                "notes": params.get("notes")
                or (f"trace:{params['trace_id']}" if params.get("trace_id") else None),
                "reuse_task_id": existing.get("id") if existing else None,
                "expected_version": existing.get("version", 1) if existing else None,
            }
            return await execute_single_caretask_mutation(
                user_id=str(user_id),
                idempotency_key=str(params["idempotency_key"]),
                request_payload=request_payload,
                mutation=mutation,
                render=lambda row: _create_result(row, query),
            )

        row = await svc.create_care_task(
            user_id=str(user_id),
            title=title,
            task_type=task_type,
            due_at=due_at,
            notes=params.get("notes") or (f"trace:{params['trace_id']}" if params.get("trace_id") else None),
            created_by="chat",
            link_reminder=due_at is not None,
            schedule_type=str(schedule_type) if schedule_type else None,
            query=query or title,
        )
        return _create_result(row, query)

    async def _list(self, params: dict, user_id: str) -> ToolResult:
        scope = str(params.get("scope") or "today").strip().lower()
        if scope not in {"today", "all"}:
            scope = "today"
        rows = await svc.list_care_tasks(
            user_id=str(user_id),
            include_terminal=bool(params.get("include_terminal")),
            limit=int(params.get("limit") or 20),
            scope=scope,
        )
        # LLM dump fields — keep consistent with task_to_dict.
        dump = [
            {
                "id": t["id"],
                "title": t["title"],
                "task_type": t.get("task_type"),
                "status": t.get("status"),
                "due_at": t.get("due_at"),
                "notes": t.get("notes"),
                "care_window_date": t.get("care_window_date"),
            }
            for t in rows
        ]
        if not rows:
            return ToolResult(
                tool_name=self.name,
                status="success",
                display_text=(
                    "今天没有待处理的照护任务"
                    if scope == "today"
                    else "当前没有待处理的照护任务"
                ),
                data={
                    "action": "caretask_list",
                    "scope": scope,
                    "tasks": [],
                    "dump": [],
                },
            )
        # Elder UI: titles; structured dump carries status/due for the model.
        lines = []
        for t in dump[:10]:
            rendered_due = format_caretask_time(t.get("due_at"))
            due = f"（{rendered_due}）" if rendered_due else ""
            lines.append(f"- {t['title']}{due}")
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text="您当前的照护任务：\n" + "\n".join(lines),
            data={
                "action": "caretask_list",
                "scope": scope,
                "tasks": rows,
                "dump": dump,
            },
        )

    async def _resolve_or_clarify(
        self,
        *,
        user_id: str,
        params: dict,
        query: str,
        action: str,
        verb_cn: str,
    ) -> ToolResult | dict[str, Any]:
        resolved = await svc.resolve_task_ref(
            user_id=str(user_id),
            task_id=str(params["task_id"]) if params.get("task_id") else None,
            title_hint=str(params.get("title") or "") or None,
            query=query or None,
        )
        if resolved.kind == "none":
            already_done = bool(getattr(resolved, "already_done", False))
            reason = (
                "already_done"
                if already_done
                else "no_active_care_task"
            )
            return ToolResult(
                tool_name=self.name,
                status="success" if action == "complete" and already_done else "failed",
                display_text=_none_resolve_display(verb_cn, resolved),
                data={
                    "reason": reason,
                    "action": (
                        "caretask_already_done"
                        if action == "complete" and already_done
                        else action
                    ),
                    "hint": getattr(resolved, "hint", None),
                    "already_done": already_done,
                },
            )
        if resolved.kind == "many":
            candidates = resolved.candidates or []
            return ToolResult(
                tool_name=self.name,
                status="needs_clarification",
                display_text=(
                    f"找到多个照护任务，请点选要{verb_cn}的那一项：\n"
                    + _format_candidates(candidates)
                ),
                data={
                    "action": f"caretask_{action}",
                    "reason": "ambiguous_task_ref",
                    "clarify_verb": verb_cn,
                    "candidates": _candidate_payload(candidates),
                },
            )
        assert resolved.task is not None
        return resolved.task

    async def _complete(self, params: dict, user_id: str, query: str) -> ToolResult:
        resolved = await self._resolve_or_clarify(
            user_id=user_id,
            params=params,
            query=query,
            action="complete",
            verb_cn="完成",
        )
        if isinstance(resolved, ToolResult):
            return resolved
        request_payload = params.get("_single_idempotency_request")
        if isinstance(request_payload, dict):
            from app.tools.caretask_batch_executor import (
                execute_single_caretask_mutation,
            )

            return await execute_single_caretask_mutation(
                user_id=str(user_id),
                idempotency_key=str(params["idempotency_key"]),
                request_payload=request_payload,
                mutation={
                    "action": "complete",
                    "task_id": str(resolved["id"]),
                    "expected_version": resolved.get("version", 1),
                },
                render=lambda row: ToolResult(
                    tool_name=self.name,
                    status="success",
                    display_text=f"已完成：{row['title']}",
                    data={"action": "caretask_complete", "task": row},
                ),
            )
        row = await svc.complete_care_task(user_id=str(user_id), task_id=str(resolved["id"]))
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text=f"已完成：{row['title']}",
            data={"action": "caretask_complete", "task": row},
        )

    async def _snooze(self, params: dict, user_id: str, query: str) -> ToolResult:
        minutes = params.get("minutes") if not query else None
        if minutes is None:
            match = re.search(r"(\d{1,4})\s*分钟", query)
            if match:
                minutes = max(1, min(int(match.group(1)), 24 * 60))
            else:
                try:
                    from app.tools.reminder_tool import detect_snooze

                    minutes = detect_snooze(query) or 30
                except Exception:
                    minutes = 30
        resolved = await self._resolve_or_clarify(
            user_id=user_id,
            params=params,
            query=query,
            action="snooze",
            verb_cn="推迟",
        )
        if isinstance(resolved, ToolResult):
            return resolved
        request_payload = params.get("_single_idempotency_request")
        if isinstance(request_payload, dict):
            from app.tools.caretask_batch_executor import (
                execute_single_caretask_mutation,
            )

            return await execute_single_caretask_mutation(
                user_id=str(user_id),
                idempotency_key=str(params["idempotency_key"]),
                request_payload=request_payload,
                mutation={
                    "action": "snooze",
                    "task_id": str(resolved["id"]),
                    "expected_version": resolved.get("version", 1),
                    "minutes": int(minutes),
                },
                render=lambda row: ToolResult(
                    tool_name=self.name,
                    status="success",
                    display_text=(
                        f"好的，我{int(row.get('snooze_minutes', minutes))}分钟后再提醒您"
                        f"{row['title']}"
                    ),
                    data={
                        "action": "caretask_snooze",
                        "task": row,
                        "snooze_minutes": int(row.get("snooze_minutes", minutes)),
                    },
                ),
            )
        row = await svc.snooze_care_task(
            user_id=str(user_id),
            task_id=str(resolved["id"]),
            minutes=int(minutes),
        )
        snooze_minutes = int(row.get("snooze_minutes", minutes))
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text=f"好的，我{snooze_minutes}分钟后再提醒您{row['title']}",
            data={
                "action": "caretask_snooze",
                "task": row,
                "snooze_minutes": snooze_minutes,
            },
        )

    async def _cancel(self, params: dict, user_id: str, query: str) -> ToolResult:
        resolved = await self._resolve_or_clarify(
            user_id=user_id,
            params=params,
            query=query,
            action="cancel",
            verb_cn="取消",
        )
        if isinstance(resolved, ToolResult):
            return resolved
        request_payload = params.get("_single_idempotency_request")
        if isinstance(request_payload, dict):
            from app.tools.caretask_batch_executor import (
                execute_single_caretask_mutation,
            )

            return await execute_single_caretask_mutation(
                user_id=str(user_id),
                idempotency_key=str(params["idempotency_key"]),
                request_payload=request_payload,
                mutation={
                    "action": "cancel",
                    "task_id": str(resolved["id"]),
                    "expected_version": resolved.get("version", 1),
                },
                render=lambda row: ToolResult(
                    tool_name=self.name,
                    status="success",
                    display_text=f"已取消：{row['title']}",
                    data={"action": "caretask_cancel", "task": row},
                ),
            )
        row = await svc.cancel_care_task(user_id=str(user_id), task_id=str(resolved["id"]))
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text=f"已取消：{row['title']}",
            data={"action": "caretask_cancel", "task": row},
        )

    async def _missed(self, params: dict, user_id: str) -> ToolResult:
        task_id = params.get("task_id")
        if not task_id:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="标记错过需要指定 task_id",
                data={"reason": "missing_task_id", "action": "missed"},
            )
        row = await svc.mark_missed(user_id=str(user_id), task_id=str(task_id))
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text=f"已标记错过：{row['title']}",
            data={"action": "caretask_missed", "task": row},
        )

    async def _batch(self, params: dict, user_id: str, query: str) -> ToolResult:
        from app.tools.caretask_batch_executor import execute_caretask_batch

        return await execute_caretask_batch(
            user_id=str(user_id),
            query=query,
            idempotency_key=str(params.get("idempotency_key") or params.get("trace_id") or ""),
            cancel_event=params.get("cancel_event"),
        )


def caretask_tool_declarations() -> list[dict[str, Any]]:
    """JSON schema declarations for Pi / Gemini FC registration."""
    tool = CareTaskTool()
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters_schema,
        }
    ]
