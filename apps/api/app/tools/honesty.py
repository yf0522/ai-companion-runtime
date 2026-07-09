"""Post-tool honesty: never claim success when a tool failed."""
from __future__ import annotations

import re

from app.tools.base import ToolResult

_SUCCESS_CLAIM_PATTERNS = [
    r"已(?:经)?(?:帮你)?(?:设置|创建|完成|推迟|取消|保存|记下)",
    r"提醒已经",
    r"任务已经",
    r"successfully\s+(created|completed|snoozed|set)",
    r"I've\s+(set|created|completed|snoozed)",
]


def response_claims_tool_success(text: str) -> bool:
    if not text:
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in _SUCCESS_CLAIM_PATTERNS)


def failed_tool_results(results: list[ToolResult] | None) -> list[ToolResult]:
    out: list[ToolResult] = []
    for r in results or []:
        if getattr(r, "status", None) in {"failed", "timeout"}:
            out.append(r)
    return out


def enforce_no_verbal_promise(
    response_text: str,
    tool_results: list[ToolResult] | None,
) -> str:
    """If any tool failed and the model claimed success, replace with honest text."""
    failed = failed_tool_results(tool_results)
    if not failed:
        return response_text

    if not response_claims_tool_success(response_text):
        # Still append a clear failure note when model ignored the failure.
        if response_text and any(
            getattr(r, "display_text", None) and r.display_text in response_text for r in failed
        ):
            return response_text
        # If model said nothing about tools, leave text but ensure honesty when it claimed success only.
        return response_text

    parts = []
    for r in failed:
        msg = r.display_text or f"{r.tool_name} 未能完成"
        parts.append(msg)
    honest = "；".join(parts)
    return f"刚才没有成功完成操作：{honest}。请稍后再试，或换个说法告诉我。"
