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


@dataclass(frozen=True)
class CareTaskSpeechAct:
    action: ActionName | None
    authorized: bool
    reason: str | None = None


_CLAUSE_SPLIT = re.compile(
    r"(?:[，,；;。]|然后|接着|并且|同时|再(?=(?:把|帮|完成|取消|推迟|看看|列出|记)))+"
)
_MUTATION_CUE = re.compile(
    r"(?:不要|别)(?:再)?提醒我|"
    r"晚点|等会|推迟|延后|分钟后|吃完|吃过|吃了(?:药)?|已吃|完成|打卡|"
    r"取消|不要了|删掉|删除|关掉|"
    r"提醒我|帮我记|记一下|记下|新增|添加|新建|创建|建立|设置|安排|改成"
)
_UNAUTHORIZED_CONTEXT = re.compile(
    r"(?:不要|别|不用|无需|不必|不需要|禁止|没有|并未|没|未|"
    r"不是(?:要|想)|不想|不打算|不会).{0,10}$|"
    r"(?:如果|假如|要是|若|万一|倘若|假设|假如说).{0,24}$|"
    r"(?:如何|怎么|怎样|是否|能否|可否|要不要|该不该|会不会|是不是|"
    r"教程|教我|说明|解释|举例|例子|比如|例如).{0,24}$|"
    r"(?:(?:新闻|报道|文章|视频)(?:里|中)?(?:提到|说|写|讲)|"
    r"(?:别人|医生|家人|他|她|他们|她们)(?:让我|叫我|要我|建议我|提到|说|讲)).{0,16}$"
)
_QUESTION_END = re.compile(r"(?:吗|么|呢|如何|怎么|怎样|怎么办)[？?]?$|[？?]$")
_QUOTE_PAIRS = {"“": "”", "「": "」", "『": "』", '"': '"', "'": "'"}
_SCHEDULED_CREATE = re.compile(
    r"^(?:请|麻烦|帮我)?(?:"
    r"(?:今天|明天|后天|每天|每日|每周).{0,24}|"
    r"(?:早上|上午|中午|下午|傍晚|晚上|夜里|凌晨)?"
    r"\d{1,2}\s*[点时:](?:\d{1,2}\s*分?)?.{0,8}"
    r")(?:吃.{0,8}药|服.{0,8}药|复诊|看病|去医院)(?:吧|啊|哦)?$"
)
_SCHEDULED_CREATE_NON_DIRECT = re.compile(
    r"[“”「」『』\"']|"
    r"(?:如果|假如|要是|若|万一|倘若|假设|据说|听说)|"
    r"(?:新闻|报道|文章|视频).{0,16}(?:提到|说|写|讲)?|"
    r"(?:医生|家人|别人|他|她|他们|她们).{0,16}(?:吃|服|复诊|看病|去医院)|"
    r"(?:不要|别|不用|无需|不必|不需要|禁止|没有|并未|没|未)"
)


def is_explicit_scheduled_create(text: str) -> bool:
    """Accept bounded schedule directives, not reports, questions, or first-person plans."""
    normalized = text.strip()
    if not _SCHEDULED_CREATE.fullmatch(normalized):
        return False
    directive = re.sub(r"^(?:请|麻烦|帮我)", "", normalized, count=1)
    return not (
        "我" in directive
        or _QUESTION_END.search(directive)
        or _SCHEDULED_CREATE_NON_DIRECT.search(directive)
    )


def _action_for_clause(clause: str) -> ActionName | None:
    if re.search(r"有哪些|有什么|列出|查看|看看|查一下", clause):
        return "list"
    if is_explicit_scheduled_create(clause):
        return "create"
    if re.search(r"晚点|等会|推迟|延后|分钟后", clause):
        return "snooze"
    if re.search(r"吃完|吃过|吃了(?:药)?|已吃|完成|打卡", clause):
        return "complete"
    if re.search(r"(?:不要|别)(?:再)?提醒我|取消|不要了|删掉|删除|关掉", clause):
        return "cancel"
    if re.search(r"提醒我|帮我记|记一下|记下|新增|添加|新建|创建|建立|设置|安排", clause):
        return "create"
    return None


def _cue_is_quoted(text: str, position: int) -> bool:
    """Return whether a cue starts inside a paired or still-open quotation."""
    stack: list[str] = []
    for char in text[:position]:
        if stack and char == stack[-1]:
            stack.pop()
        elif char in _QUOTE_PAIRS:
            stack.append(_QUOTE_PAIRS[char])
    return bool(stack)


def _mutation_cues(text: str) -> list[re.Match[str]]:
    return list(_MUTATION_CUE.finditer(text))


def _mutation_is_authorized(clause: str, cue: re.Match[str]) -> bool:
    prefix = clause[: cue.start()]
    if _cue_is_quoted(clause, cue.start()):
        return False
    if _UNAUTHORIZED_CONTEXT.search(prefix):
        return False
    if _QUESTION_END.search(clause.strip()):
        return False
    return True


def classify_caretask_speech_act(clause: str) -> CareTaskSpeechAct:
    """Classify one user clause without treating mention as mutation authority."""
    text = clause.strip()
    action = _action_for_clause(text)
    if action is None:
        return CareTaskSpeechAct(None, False, "no_supported_action")
    if action == "list":
        return CareTaskSpeechAct("list", True)
    if action == "create" and is_explicit_scheduled_create(text):
        return CareTaskSpeechAct("create", True)
    cues = _mutation_cues(text)
    if len(cues) != 1:
        return CareTaskSpeechAct(action, False, "ambiguous_mutation_cues")
    if not _mutation_is_authorized(text, cues[0]):
        return CareTaskSpeechAct(action, False, "mutation_not_authorized")
    return CareTaskSpeechAct(action, True)


def _independently_authorized_action(text: str) -> bool:
    return classify_caretask_speech_act(text).authorized


def _split_bounded_conjunctions(part: str) -> list[str]:
    """Split 和/并 only when each resulting side is an independently valid action."""
    for match in re.finditer(r"和|并", part):
        left = part[: match.start()].strip()
        right = part[match.end() :].strip()
        if (
            left
            and right
            and _independently_authorized_action(left)
            and _independently_authorized_action(right)
        ):
            return [left, right]
    return [part]


def _clauses(query: str) -> list[str]:
    cleaned = re.sub(r"^(?:请|麻烦|先)", "", query.strip())
    clauses: list[str] = []
    for part in _CLAUSE_SPLIT.split(cleaned):
        part = part.strip()
        if not part:
            continue
        bounded = _split_bounded_conjunctions(part)
        if len(bounded) > 1:
            clauses.extend(bounded)
            continue
        # Production transcripts often contain only spaces between complete
        # imperative clauses. Split those only when every piece independently
        # carries an executable cue; ordinary spaces inside one clause remain.
        words = [piece.strip() for piece in re.split(r"\s+", part) if piece.strip()]
        if len(words) >= 2 and sum(_action_for_clause(piece) is not None for piece in words) >= 2:
            clauses.extend(words)
        else:
            clauses.append(part)
    return clauses


def detect_compound_caretask(query: str) -> bool:
    # Detection is intentionally broader than authorization. Unsafe compound
    # turns must still enter the deterministic batch preflight and fail closed,
    # rather than falling through to a model-selected single mutation.
    return len(_mutation_cues(query)) >= 2 or sum(
        _action_for_clause(part) is not None for part in _clauses(query)
    ) >= 2


def plan_caretask_batch(query: str, *, now: datetime | None = None) -> CareTaskBatchPlan:
    del now  # The caller freezes time; schedule parsing consumes it during preflight.
    actions: list[PlannedCareAction] = []
    clauses = _clauses(query)
    discovered_mutations = sum(
        1 if is_explicit_scheduled_create(clause) else len(_mutation_cues(clause))
        for clause in clauses
    )
    planned_mutations = 0
    for clause in clauses:
        speech_act = classify_caretask_speech_act(clause)
        action = speech_act.action
        if action is None:
            if re.search(r"提醒|任务|吃药|复诊|完成|取消|推迟|新增|创建|改成|剂量|\d+片|[一二两三四五六七八九十]+片", clause):
                return CareTaskBatchPlan((), "invalid", "unsupported_or_unmatched_cue")
            continue
        if action != "list":
            if not speech_act.authorized:
                return CareTaskBatchPlan((), "needs_clarification", speech_act.reason)
            planned_mutations += 1
        minutes = None
        if action == "snooze":
            match = re.search(r"(\d{1,4})\s*分钟", clause)
            minutes = int(match.group(1)) if match else 30
            if not 1 <= minutes <= 1440:
                return CareTaskBatchPlan((), "invalid", "invalid_snooze_minutes")
        actions.append(PlannedCareAction(len(actions), action, clause, minutes=minutes))
    if discovered_mutations != planned_mutations:
        return CareTaskBatchPlan((), "needs_clarification", "unplanned_mutation_cue")
    if len(actions) < 2:
        return CareTaskBatchPlan(tuple(actions), "invalid", "not_compound")
    return CareTaskBatchPlan(tuple(actions))
