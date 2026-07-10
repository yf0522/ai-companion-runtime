"""Refuse rules for memory.note — never store Rx/dose/escalation as memory."""
from __future__ import annotations

import re
from dataclasses import dataclass

# Prescription / dose mutation — CareTask is the SoT for medication agreements.
_PRESCRIPTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"剂量|用量|几毫克|\d+\s*mg|\d+\s*毫克|(?:\d+|[一二两三四五六七八九十半]+)\s*片",
        r"减药|加药|停药|换药|改药|调整用药|改剂量|改用量|改成.{0,12}(?:片|粒|毫克|mg)",
        r"处方|开药|配药|药方",
        r"(?:每天|每日|早晚).{0,8}(?:吃|服).{0,12}(?:片|粒|毫克|mg)",
        r"胰岛素.{0,6}(?:单位|U\b)",
    )
)

# Escalation / notification policy — never mutate via memory tools.
_ESCALATION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"升级(?:策略|规则|通知|告警)?",
        r"改(?:通知|告警|提醒)规则",
        r"通知家人|呼叫家人|报警给|escalat",
        r"记住.{0,12}(?:通知|升级|告警)",
        r"以后.*(?:自动通知|自动升级|直接通知家人)",
    )
)

REFUSAL_DISPLAY = {
    "prescription_content": (
        "用药剂量和处方约定请走照护任务（CareTask）或由家人/医生确认，"
        "我不会把这类内容记成长期记忆。"
    ),
    "escalation_mutation": (
        "通知升级和告警规则不能记成记忆；如需调整请在照护设置里修改，"
        "我不会通过记忆工具改这些规则。"
    ),
}


@dataclass(frozen=True)
class RefuseDecision:
    refused: bool
    code: str | None = None
    display_text: str = ""


def refuse_memory_note(text: str) -> RefuseDecision:
    """Return a refuse decision if ``text`` must not be stored as long-term memory."""
    content = (text or "").strip()
    if not content:
        return RefuseDecision(refused=False)
    for pattern in _PRESCRIPTION_PATTERNS:
        if pattern.search(content):
            return RefuseDecision(
                refused=True,
                code="prescription_content",
                display_text=REFUSAL_DISPLAY["prescription_content"],
            )
    for pattern in _ESCALATION_PATTERNS:
        if pattern.search(content):
            return RefuseDecision(
                refused=True,
                code="escalation_mutation",
                display_text=REFUSAL_DISPLAY["escalation_mutation"],
            )
    return RefuseDecision(refused=False)
