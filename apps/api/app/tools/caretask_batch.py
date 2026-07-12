"""Deterministic, server-owned planning for compound CareTask utterances."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

ActionName = Literal["list", "create", "complete", "snooze", "cancel"]


@dataclass(frozen=True)
class PlannedCareAction:
    index: int
    action: ActionName
    query: str
    title_hint: str | None = None
    minutes: int | None = None
    expected_version: int | None = None
    task_id: str | None = None


@dataclass(frozen=True)
class CareTaskBatchPlan:
    actions: tuple[PlannedCareAction, ...] = field(default_factory=tuple)
    status: Literal["planned", "needs_clarification", "invalid"] = "planned"
    reason: str | None = None


_CLAUSE_SPLIT = re.compile(r"(?:[，,；;。]|然后|接着|并且|同时|再(?=(?:把|帮|完成|取消|推迟|看看|列出|记)))+")


def _action_for_clause(clause: str) -> ActionName | None:
    if re.search(r"有哪些|有什么|列出|查看|看看|查一下", clause):
        return "list"
    if re.search(r"晚点|等会|推迟|延后|分钟后", clause):
        return "snooze"
    if re.search(r"吃完|吃过|完成|打卡", clause):
        return "complete"
    if re.search(r"取消|不要了|删掉|删除", clause):
        return "cancel"
    if re.search(r"提醒我|帮我记|记一下|记下|新增|添加|新建|创建|设置|安排", clause):
        return "create"
    return None


def _clauses(query: str) -> list[str]:
    cleaned = re.sub(r"^(?:请|麻烦|先)", "", query.strip())
    return [part.strip() for part in _CLAUSE_SPLIT.split(cleaned) if part.strip()]


def detect_compound_caretask(query: str) -> bool:
    return sum(_action_for_clause(part) is not None for part in _clauses(query)) >= 2


def plan_caretask_batch(query: str, *, now: datetime | None = None) -> CareTaskBatchPlan:
    del now  # The caller freezes time; schedule parsing consumes it during preflight.
    actions: list[PlannedCareAction] = []
    for clause in _clauses(query):
        action = _action_for_clause(clause)
        if action is None:
            if re.search(r"提醒|任务|吃药|复诊|完成|取消|推迟|新增|创建", clause):
                return CareTaskBatchPlan(tuple(actions), "invalid", "unsupported_or_unmatched_cue")
            continue
        minutes = None
        if action == "snooze":
            match = re.search(r"(\d{1,4})\s*分钟", clause)
            minutes = int(match.group(1)) if match else 30
            if not 1 <= minutes <= 1440:
                return CareTaskBatchPlan(tuple(actions), "invalid", "invalid_snooze_minutes")
        actions.append(PlannedCareAction(len(actions), action, clause, minutes=minutes))
    if len(actions) < 2:
        return CareTaskBatchPlan(tuple(actions), "invalid", "not_compound")
    return CareTaskBatchPlan(tuple(actions))
