"""CareTask ToolBase — create/list/complete/snooze (+ cancel/missed)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

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


def _parse_due_at(text: str) -> datetime | None:
    """Reuse ReminderTool time parsing when available."""
    try:
        from app.tools.reminder_tool import parse_time_from_text

        t = parse_time_from_text(text)
        if t is None:
            return None
        now = datetime.utcnow()
        due = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if due <= now:
            due = due + timedelta(days=1)
        return due
    except Exception:
        return None


def _infer_task_type(text: str) -> str:
    if re.search(r"复诊|预约|看病|医院|门诊", text):
        return "appointment"
    return "medication"


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
    if re.search(r"晚点再|等会儿再|推迟|再提醒|分钟后再", query):
        return "snooze"
    if re.search(r"吃完了|已经吃|完成了|打卡|确认.*吃", query):
        return "complete"
    if re.search(r"取消|不要了|删掉", query):
        return "cancel"
    if re.search(r"有哪些|列出|我的.*任务|待办|还没吃", query):
        return "list"
    return "create"


def _format_candidates(candidates: list[dict[str, Any]]) -> str:
    """Elder-facing candidate list — titles only, no status/id jargon."""
    lines = []
    for i, t in enumerate(candidates[:8], start=1):
        due = f"（{t['due_at']}）" if t.get("due_at") else ""
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
        return f"您已经有{label}的提醒了，我帮您更新了时间，没有重复创建。"
    return f"您已经有{label}的提醒了，我帮您沿用，没有重复创建。"


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
        "create, list, complete, snooze, cancel. Reminder is scheduling projection."
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
            "query": {"type": "string", "description": "Natural language fallback"},
        },
        "required": ["action"],
    }

    async def execute(self, params: dict) -> ToolResult:
        action = str(params.get("action") or "").strip().lower()
        query = str(params.get("query") or "")
        if not action or action == "auto":
            action = _infer_action_from_query(query)
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
                data={"reason": "invalid_transition", "error": str(e), "action": action},
            )
        except LookupError as e:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="没有找到对应的照护任务",
                data={"reason": str(e), "action": action},
            )
        except Exception as e:
            logger.error("CareTask tool failed: %s", e, exc_info=True)
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="照护任务处理失败，请稍后重试",
                data={"reason": "exception", "error": str(e), "action": action},
            )

    async def _create(self, params: dict, user_id: str, query: str) -> ToolResult:
        title = str(params.get("title") or "").strip()
        task_type = str(params.get("task_type") or _infer_task_type(query or title))
        if not title:
            title = _infer_title(query, task_type)
        due_at = None
        if params.get("due_at"):
            try:
                due_at = datetime.fromisoformat(str(params["due_at"]).replace("Z", "+00:00")).replace(
                    tzinfo=None
                )
            except ValueError:
                due_at = None
        if due_at is None and query:
            due_at = _parse_due_at(query)

        schedule_type = params.get("schedule_type")
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
        action = row.pop("_action", "caretask_create")
        schedule_updated = bool(row.pop("_schedule_updated", False))
        st = row.get("schedule_type")
        if action == "caretask_reuse":
            if schedule_updated:
                device_action = "caretask_schedule_updated"
            else:
                device_action = "caretask_reuse"
            return ToolResult(
                tool_name=self.name,
                status="success",
                display_text=_reuse_display(row["title"], schedule_updated=schedule_updated),
                data={
                    "action": device_action,
                    "task": row,
                    "schedule_updated": schedule_updated,
                    "schedule_type": st,
                    "query": query,
                },
            )
        if action == "caretask_clarify_create":
            candidates = row.get("candidates") or []
            return ToolResult(
                tool_name=self.name,
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
        due_txt = f"（{row['due_at']}）" if row.get("due_at") else ""
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text=f"好的，已记下：{row['title']}{due_txt}",
            data={
                "action": "caretask_create",
                "task": row,
                "schedule_type": st,
                "query": query,
            },
        )

    async def _list(self, params: dict, user_id: str) -> ToolResult:
        rows = await svc.list_care_tasks(
            user_id=str(user_id),
            include_terminal=bool(params.get("include_terminal")),
            limit=int(params.get("limit") or 20),
        )
        if not rows:
            return ToolResult(
                tool_name=self.name,
                status="success",
                display_text="当前没有待处理的照护任务",
                data={"action": "caretask_list", "tasks": []},
            )
        # Elder UI: titles only; status stays in structured data for Trace.
        lines = [f"- {t['title']}" for t in rows[:10]]
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text="您当前的照护任务：\n" + "\n".join(lines),
            data={"action": "caretask_list", "tasks": rows},
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
        row = await svc.complete_care_task(user_id=str(user_id), task_id=str(resolved["id"]))
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text=f"已完成：{row['title']}",
            data={"action": "caretask_complete", "task": row},
        )

    async def _snooze(self, params: dict, user_id: str, query: str) -> ToolResult:
        minutes = params.get("minutes")
        if minutes is None:
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
