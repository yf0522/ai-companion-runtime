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
    m = re.search(r"(?:提醒我|记得|帮我)?(.{2,24}?)(?:吧|啊|哦)?$", text.strip())
    raw = (m.group(1) if m else text).strip()
    raw = re.sub(r"^(每天|明天|今天|晚上|早上|下午)", "", raw).strip()
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
        if not user_id and action != "list":
            # list also needs user; fail consistently
            pass
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
                return await self._complete(params, user_id)
            if action == "snooze":
                return await self._snooze(params, user_id, query)
            if action == "cancel":
                return await self._cancel(params, user_id)
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
                due_at = datetime.fromisoformat(str(params["due_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                due_at = None
        if due_at is None and query:
            due_at = _parse_due_at(query)

        row = await svc.create_care_task(
            user_id=str(user_id),
            title=title,
            task_type=task_type,
            due_at=due_at,
            notes=params.get("notes") or (f"trace:{params['trace_id']}" if params.get("trace_id") else None),
            created_by="chat",
            link_reminder=due_at is not None,
        )
        due_txt = f"（{row['due_at']}）" if row.get("due_at") else ""
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text=f"已创建照护任务：{row['title']}{due_txt}，状态 {row['status']}",
            data={"action": "caretask_create", "task": row},
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
        lines = [f"- {t['title']} [{t['status']}]" for t in rows[:10]]
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text="照护任务：\n" + "\n".join(lines),
            data={"action": "caretask_list", "tasks": rows},
        )

    async def _complete(self, params: dict, user_id: str) -> ToolResult:
        task_id = params.get("task_id")
        if not task_id:
            rows = await svc.list_care_tasks(user_id=str(user_id), limit=1)
            if not rows:
                return ToolResult(
                    tool_name=self.name,
                    status="failed",
                    display_text="没有可完成的照护任务",
                    data={"reason": "no_active_care_task", "action": "complete"},
                )
            task_id = rows[0]["id"]
        row = await svc.complete_care_task(user_id=str(user_id), task_id=str(task_id))
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
        row = await svc.snooze_care_task(
            user_id=str(user_id),
            task_id=str(params["task_id"]) if params.get("task_id") else None,
            minutes=int(minutes),
        )
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text=f"好的，我{row.get('snooze_minutes', minutes)}分钟后再提醒您{row['title']}",
            data={"action": "caretask_snooze", "task": row},
        )

    async def _cancel(self, params: dict, user_id: str) -> ToolResult:
        task_id = params.get("task_id")
        if not task_id:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="取消任务需要指定 task_id",
                data={"reason": "missing_task_id", "action": "cancel"},
            )
        row = await svc.cancel_care_task(user_id=str(user_id), task_id=str(task_id))
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
