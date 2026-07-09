"""Post-tool honesty: never claim success when a tool failed / clarified / reused."""
from __future__ import annotations

import re

from app.tools.base import ToolResult

_SUCCESS_CLAIM_PATTERNS = [
    r"已(?:经)?(?:为您|帮你|帮您)?(?:设置|创建|完成|推迟|取消|保存|记下|记录)",
    r"已经为您(?:取消|记录|创建|设置)",
    r"提醒已经",
    r"任务已经",
    r"successfully\s+(created|completed|snoozed|set)",
    r"I've\s+(set|created|completed|snoozed)",
]

# Model often says 「我已经提醒你…了」 as if the alarm fired now.
_FALSE_REMIND_NOW_PATTERNS = [
    r"我已经提醒(?:你|您)",
    r"已经提醒(?:你|您)(?:吃|服用)",
    r"已(?:经)?提醒过(?:你|您)",
]

# Technical dumps that must never appear in elder chat bubbles.
_TECH_JARGON_PATTERNS = [
    r"状态\s*pending",
    r"\bpending\b",
    r"未重复创建",
    r"已有相同照护任务",
    r"id\s*[=:：]\s*[0-9a-f-]{8,}",
    r"\[pending\]",
    r"caretask_",
]


def response_claims_tool_success(text: str) -> bool:
    if not text:
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in _SUCCESS_CLAIM_PATTERNS)


def response_claims_reminded_now(text: str) -> bool:
    if not text:
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in _FALSE_REMIND_NOW_PATTERNS)


def response_has_tech_jargon(text: str) -> bool:
    if not text:
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in _TECH_JARGON_PATTERNS)


def failed_tool_results(results: list[ToolResult] | None) -> list[ToolResult]:
    out: list[ToolResult] = []
    for r in results or []:
        if getattr(r, "status", None) in {"failed", "timeout", "needs_clarification"}:
            out.append(r)
    return out


def _reuse_results(results: list[ToolResult] | None) -> list[ToolResult]:
    out: list[ToolResult] = []
    for r in results or []:
        data = getattr(r, "data", None) or {}
        action = data.get("action") if isinstance(data, dict) else None
        if action in {"caretask_reuse", "caretask_schedule_updated"}:
            out.append(r)
    return out


def enforce_no_verbal_promise(
    response_text: str,
    tool_results: list[ToolResult] | None,
) -> str:
    """If any tool failed/needs clarification and the model claimed success, rewrite.

    Also rewrite false 「已经记录了 / 我已经提醒你了」 when the tool only reused
    an existing CareTask (no new create / no fire-now).
    """
    failed = failed_tool_results(tool_results)
    if failed:
        if response_claims_tool_success(response_text):
            clarify = [r for r in failed if getattr(r, "status", None) == "needs_clarification"]
            if clarify and all(getattr(r, "status", None) == "needs_clarification" for r in failed):
                parts = [r.display_text or f"{r.tool_name} 需要确认" for r in clarify]
                return "；".join(parts)

            parts = []
            for r in failed:
                msg = r.display_text or f"{r.tool_name} 未能完成"
                parts.append(msg)
            honest = "；".join(parts)
            return f"刚才没有成功完成操作：{honest}。请稍后再试，或换个说法告诉我。"

        if response_text and any(
            getattr(r, "display_text", None) and r.display_text in response_text for r in failed
        ):
            return response_text
        return response_text

    reuse = _reuse_results(tool_results)
    if not reuse:
        return response_text

    needs_rewrite = (
        response_claims_tool_success(response_text)
        or response_claims_reminded_now(response_text)
        or response_has_tech_jargon(response_text)
    )
    if not needs_rewrite:
        return response_text

    parts = [
        r.display_text or "您已经有这个提醒了，我帮您沿用，没有重复创建。"
        for r in reuse
    ]
    return "；".join(parts)
