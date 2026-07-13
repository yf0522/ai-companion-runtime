"""Memory ToolBase — action=recall|note (CareTask-style single tool)."""
from __future__ import annotations

import logging
import re
from typing import Any

from app.memory.adapter import get_memory_adapter
from app.tools.base import ToolBase, ToolResult

logger = logging.getLogger(__name__)

_ACTION_ALIASES = {
    "recall": "recall",
    "remember": "recall",
    "search": "recall",
    "get": "recall",
    "note": "note",
    "write": "note",
    "save": "note",
    "store": "note",
}

_EXPLICIT_NOTE_PATTERN = re.compile(r"以后记得|帮我记住|记一下|请记住|别忘了")


def is_explicit_memory_note(query: str | None) -> bool:
    return bool(_EXPLICIT_NOTE_PATTERN.search(str(query or "")))


def _infer_action(query: str) -> str:
    if is_explicit_memory_note(query):
        return "note"
    if re.search(r"你还记得|记得我|我喜欢什么|我说过", query):
        return "recall"
    return "recall"


def _infer_category(text: str) -> str:
    if re.search(r"叫我|称呼|语气|说话方式|别太|温柔|简洁", text):
        return "persona_style"
    if re.search(r"住在|家里|小区|门牌|邻居|作息|几点睡", text):
        return "household_fact"
    if re.search(r"喜欢|不喜欢|偏好|爱吃|讨厌", text):
        return "preference"
    if re.search(r"打电话|语音|文字|慢点说|大声", text):
        return "communication_habit"
    return "preference"


class MemoryTool(ToolBase):
    name = "memory"
    description = (
        "Long-term continuity memory (not CareTask). "
        "action=recall: read consent-granted preference/fact fragments (empty on timeout/crisis). "
        "action=note: write preference/household/communication/persona facts with pending consent "
        "in production; refuses prescription/dose/escalation (use caretask for meds). "
        "Never mutates CareTask or escalation policies."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["recall", "note"],
                "description": "recall = read authorized memories; note = write preference/fact",
            },
            "query_intent": {
                "type": "string",
                "description": "What to recall (optional keyword/intent)",
            },
            "summary": {
                "type": "string",
                "description": "Fact/preference to remember (note)",
            },
            "category": {
                "type": "string",
                "enum": [
                    "preference",
                    "household_fact",
                    "communication_habit",
                    "persona_style",
                ],
            },
            "time_from": {"type": "string", "description": "ISO lower bound (recall)"},
            "time_to": {"type": "string", "description": "ISO upper bound (recall)"},
            "limit": {"type": "integer", "description": "Max fragments (default 5)"},
            "explicit_user_request": {
                "type": "boolean",
                "description": "Used only when query is absent; query text is authoritative",
            },
            "query": {"type": "string", "description": "Natural language fallback"},
        },
        "required": ["action"],
    }

    async def execute(self, params: dict) -> ToolResult:
        action = str(params.get("action") or "").strip().lower()
        query = str(params.get("query") or "")
        if not action or action == "auto":
            action = _infer_action(query)
        action = _ACTION_ALIASES.get(action, action)

        user_id = params.get("user_id")
        if not user_id:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="无法处理记忆：缺少用户信息",
                data={"reason": "missing_user", "action": action},
            )

        risk_blocked = bool(params.get("risk_blocked"))
        risk_level = params.get("risk_level")
        adapter = get_memory_adapter()

        try:
            if action == "recall":
                return await self._recall(adapter, params, str(user_id), query, risk_blocked, risk_level)
            if action == "note":
                return await self._note(adapter, params, str(user_id), query, risk_blocked, risk_level)
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text=f"不支持的记忆操作：{action}",
                data={"reason": "unknown_action", "action": action},
            )
        except Exception as exc:
            logger.error(
                "Memory tool failed error_class=%s code=memory_tool_failed",
                type(exc).__name__,
            )
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="记忆处理失败，请稍后重试",
                data={
                    "reason": "memory_tool_failed",
                    "error_class": type(exc).__name__,
                    "error_code": "memory_tool_failed",
                    "action": action,
                },
            )

    async def _recall(
        self,
        adapter: Any,
        params: dict,
        user_id: str,
        query: str,
        risk_blocked: bool,
        risk_level: Any,
    ) -> ToolResult:
        result = await adapter.recall(
            user_id=user_id,
            query_intent=str(params.get("query_intent") or query or ""),
            time_from=params.get("time_from"),
            time_to=params.get("time_to"),
            limit=int(params.get("limit") or 5),
            risk_blocked=risk_blocked,
            risk_level=str(risk_level) if risk_level else None,
        )
        status = "success" if result.status == "success" else (
            "timeout" if result.status == "timeout" else "success"
        )
        # Empty/timeout still success-shaped for Pi honesty: display may be empty.
        if result.status in {"empty", "timeout", "unauthorized"}:
            status = "success" if result.status == "empty" else result.status
            if result.status == "unauthorized":
                status = "failed"
        return ToolResult(
            tool_name=self.name,
            status=status if status in {"success", "failed", "timeout"} else "success",
            display_text=result.display_text,
            data={
                "action": "memory_recall",
                "status": result.status,
                "fragments": result.fragments,
                "degraded": result.degraded,
                **(result.data or {}),
            },
        )

    async def _note(
        self,
        adapter: Any,
        params: dict,
        user_id: str,
        query: str,
        risk_blocked: bool,
        risk_level: Any,
    ) -> ToolResult:
        # When present, query is the actual user turn injected by the bridge;
        # it is authoritative over model-provided summary/explicit flags.
        # Keep the legacy fields only for trusted non-sidecar callers that do
        # not provide query.
        if query.strip():
            summary = query.strip()
            explicit = bool(_EXPLICIT_NOTE_PATTERN.search(query))
        else:
            summary = str(params.get("summary") or "").strip()
            explicit = bool(params.get("explicit_user_request"))
        category = str(params.get("category") or _infer_category(summary))
        result = await adapter.note(
            user_id=user_id,
            summary=summary,
            category=category,
            explicit_user_request=bool(explicit),
            session_id=params.get("session_id"),
            trace_id=params.get("trace_id"),
            risk_blocked=risk_blocked,
            risk_level=str(risk_level) if risk_level else None,
        )
        if result.status == "refused":
            return ToolResult(
                tool_name=self.name,
                status="success",
                display_text=result.display_text,
                data={
                    "action": "memory_note",
                    "status": "refused",
                    "refusal_code": result.refusal_code,
                    **(result.data or {}),
                },
            )
        if result.status == "failed":
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text=result.display_text,
                data={"action": "memory_note", "status": "failed", **(result.data or {})},
            )
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text=result.display_text,
            data={
                "action": "memory_note",
                "status": result.status,
                "memory_id": result.memory_id,
                **(result.data or {}),
            },
        )


def memory_tool_declarations() -> list[dict[str, Any]]:
    tool = MemoryTool()
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters_schema,
        }
    ]
