"""CareTask domain: state machine + persistence. Reminder = scheduling projection."""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from app.tools.device_projection import infer_schedule_type_from_utterance

logger = logging.getLogger(__name__)

CARE_TASK_STATUSES = frozenset(
    {"pending", "due", "done", "snoozed", "missed", "cancelled"}
)
ACTIVE_STATUSES = frozenset({"pending", "due", "snoozed"})
TERMINAL_STATUSES = frozenset({"done", "missed", "cancelled"})

_TITLE_NOISE = re.compile(
    r"^(?:提醒我|记得|帮我|请|麻烦|给我)?(?:每天|明天|今天|晚上|早上|下午|中午)?"
)
_TITLE_TRAIL = re.compile(r"(?:吧|啊|哦|呀|呢|了)+$")
_WHITESPACE = re.compile(r"\s+")
# Schedule / clock noise that must not split medication identity fingerprints.
_SCHEDULE_NOISE = re.compile(
    r"(?:每天|每日|每周|明天|今天|后天)?"
    r"(?:早上|上午|中午|下午|傍晚|晚上|夜里|凌晨)?"
    r"(?:\d{1,2}\s*[点时:](?:\d{1,2}\s*分?)?|"
    r"[零一二三四五六七八九十两]+\s*[点时](?:\s*[零一二三四五六七八九十]+\s*分?)?)?"
)
_REMINDER_FILLER = re.compile(r"(?:提醒我|记得|帮我记一下|帮我记下|帮我|请帮我|给我|记一下|记下|请|麻烦)")
# Mutate verbs / category noise — strip before resolve matching so
# 「取消吃药提醒」 does not silently bind to a single generic 「吃药」 title.
_RESOLVE_ACTION_PREFIX = re.compile(
    r"^(?:请|麻烦|帮我|给我)?(?:取消|不要了|不要|删掉|删除|完成|打卡|推迟|延后)"
)
_RESOLVE_ACTION_SUFFIX = re.compile(r"(?:的)?(?:提醒|任务|闹钟)+$")
# Complete / done phrasing: 「降压药我吃过了」 → hint 「降压药」
# Match with or without trailing 了 (normalize_title may strip 了 first).
_RESOLVE_DONE_SUFFIX = re.compile(
    r"(?:我)?(?:已经)?(?:"
    r"吃过了?|吃完了?|吃了|服用了?|打卡了?|完成了?|做过了?|好了"
    r")$"
)
_TASK_ID_IN_QUERY = re.compile(
    r"(?:id\s*[=:：]\s*)?"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_GENERIC_MED_HINTS = frozenset(
    {
        "",
        "药",
        "吃药",
        "服药",
        "用药",
        "吃药提醒",
        "服药提醒",
        "用药提醒",
        "提醒",
        "那个",
        "这个",
    }
)

# Allowed transitions: from -> to
_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"due", "done", "snoozed", "missed", "cancelled"}),
    "due": frozenset({"done", "snoozed", "missed", "cancelled"}),
    "snoozed": frozenset({"pending", "due", "done", "missed", "cancelled"}),
    "done": frozenset(),
    "missed": frozenset({"done", "cancelled"}),
    "cancelled": frozenset(),
}


class CareTaskTransitionError(ValueError):
    """Invalid CareTask state transition."""


class StaleCareTaskVersionError(ValueError):
    """CareTask version no longer matches the caller's expected version."""

    def __init__(self, *, expected_version: int, current_version: int) -> None:
        self.expected_version = expected_version
        self.current_version = current_version
        super().__init__(
            f"stale CareTask version: expected {expected_version}, current {current_version}"
        )


def normalize_user_id(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except (ValueError, AttributeError, TypeError):
        return uuid.uuid5(uuid.NAMESPACE_DNS, str(user_id))


def infer_initial_status(due_at: datetime | None, now: datetime | None = None) -> str:
    now = now or datetime.utcnow()
    if due_at is not None and due_at <= now:
        return "due"
    return "pending"


def can_transition(from_status: str, to_status: str) -> bool:
    if from_status not in CARE_TASK_STATUSES or to_status not in CARE_TASK_STATUSES:
        return False
    return to_status in _TRANSITIONS.get(from_status, frozenset())


def assert_transition(from_status: str, to_status: str) -> None:
    if not can_transition(from_status, to_status):
        raise CareTaskTransitionError(f"cannot transition {from_status} → {to_status}")


def refresh_status(status: str, due_at: datetime | None, snooze_until: datetime | None, now: datetime | None = None) -> str:
    """Derive due/missed/pending from clocks without mutating terminal states."""
    now = now or datetime.utcnow()
    if status in TERMINAL_STATUSES:
        return status
    if status == "snoozed":
        if snooze_until and snooze_until <= now:
            if due_at and due_at <= now:
                return "due"
            return "pending"
        return "snoozed"
    if due_at is None:
        return status if status in ACTIVE_STATUSES else "pending"
    if due_at <= now:
        # Overdue window: still actionable as due; callers may mark missed explicitly.
        return "due"
    return "pending"


def task_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "title": row.title,
        "task_type": row.task_type,
        "status": row.status,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "snooze_until": row.snooze_until.isoformat() if row.snooze_until else None,
        "reminder_id": str(row.reminder_id) if row.reminder_id else None,
        "notes": row.notes,
        "created_by": row.created_by,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "version": getattr(row, "version", 1),
        "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
    }


def normalize_title(title: str) -> str:
    """Normalize CareTask title for identity matching (ignore schedule wording)."""
    text = (title or "").strip()
    text = _WHITESPACE.sub("", text)
    # Drop schedule / clock fragments anywhere (elder UX: same med = same task).
    text = _SCHEDULE_NOISE.sub("", text)
    text = _REMINDER_FILLER.sub("", text)
    text = _TITLE_NOISE.sub("", text)
    text = _TITLE_TRAIL.sub("", text)
    # Strip leftover create prefixes that survive inference
    for prefix in (
        "提醒我",
        "记得",
        "帮我记一下",
        "帮我记下",
        "帮我",
        "请帮我",
        "给我",
        "记一下",
        "记下",
    ):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    if "药" in text:
        text = re.sub(r"^(?:服用|服药)", "吃", text)
    text = text.lower()
    return text.strip() or (title or "").strip()[:80]


def due_bucket(due_at: datetime | None) -> str | None:
    if due_at is None:
        return None
    return due_at.strftime("%Y-%m-%d")


def title_fingerprint(title: str, task_type: str, due_at: datetime | None = None) -> str:
    """Identity fingerprint: task_type + normalized title.

    ``due_at`` is accepted for API compatibility but intentionally ignored —
    same medication/appointment title must reuse even when schedule differs.
    """
    _ = due_at
    return f"{task_type}|{normalize_title(title)}"


def identity_key(title: str, task_type: str) -> str:
    return title_fingerprint(title, task_type, None)


def _token_overlap(a: str, b: str) -> float:
    """Simple CJK/latin token overlap for near-duplicate detection."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.9
    # Character bigram Jaccard for short Chinese titles
    def bigrams(s: str) -> set[str]:
        if len(s) < 2:
            return {s}
        return {s[i : i + 2] for i in range(len(s) - 1)}

    ba, bb = bigrams(na), bigrams(nb)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def extract_resolve_hint(title_hint: str | None, query: str | None) -> str:
    """Normalize a mutate utterance into a title/category hint.

    Strips cancel/complete verbs and trailing 「提醒」 so category phrases
    like 「取消吃药提醒」 become the generic med hint 「吃药」.
    Also strips done phrasing: 「降压药我吃过了」 → 「降压药」.
    """
    # Strip done/cancel phrasing on raw text first so normalize_title's
    # trailing-「了」 trim cannot leave a dangling 「吃过」.
    raw = _WHITESPACE.sub("", (title_hint or query or "").strip())
    raw = _RESOLVE_ACTION_PREFIX.sub("", raw)
    raw = _RESOLVE_DONE_SUFFIX.sub("", raw)
    raw = _RESOLVE_ACTION_SUFFIX.sub("", raw)
    text = normalize_title(raw)
    text = _RESOLVE_ACTION_PREFIX.sub("", text)
    text = _RESOLVE_DONE_SUFFIX.sub("", text)
    text = _RESOLVE_ACTION_SUFFIX.sub("", text)
    text = text.strip()
    # Second pass: leftover filler after verb strip (e.g. 取消提醒我吃药)
    text = normalize_title(text)
    text = _RESOLVE_DONE_SUFFIX.sub("", text)
    text = _RESOLVE_ACTION_SUFFIX.sub("", text)
    return text.strip()


def extract_task_id_from_query(query: str | None) -> str | None:
    """Parse an explicit CareTask UUID from clarify-button follow-ups."""
    if not query:
        return None
    m = _TASK_ID_IN_QUERY.search(query)
    return m.group(1) if m else None


def is_generic_med_hint(hint: str) -> bool:
    """True when the referent is category-level, not a specific med title."""
    h = (hint or "").strip()
    if h in _GENERIC_MED_HINTS:
        return True
    # Very short / only 「吃…药」 without a drug name → still category.
    if h in {"吃药", "服药", "用药"}:
        return True
    return False


@dataclass
class ResolveResult:
    kind: Literal["one", "many", "none"]
    task: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] | None = None
    hint: str | None = None
    already_done: bool = False


def _parse_row_due(row: dict[str, Any]) -> datetime | None:
    if not row.get("due_at"):
        return None
    try:
        return datetime.fromisoformat(str(row["due_at"]).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return None


async def find_active_by_fingerprint(
    *,
    user_id: str,
    title: str,
    task_type: str,
    due_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Active identity match: same task_type + normalized title (due ignored)."""
    _ = due_at
    rows = await list_care_tasks(user_id=user_id, include_terminal=False, limit=50)
    target = identity_key(title, task_type)
    for row in rows:
        if row.get("status") not in ACTIVE_STATUSES:
            continue
        if identity_key(row["title"], row.get("task_type") or task_type) == target:
            return row
    return None


async def find_near_duplicate_candidates(
    *,
    user_id: str,
    title: str,
    task_type: str,
    due_at: datetime | None = None,
    threshold: float = 0.55,
) -> list[dict[str, Any]]:
    """Near-dup active tasks with similar-but-not-identical titles (clarify)."""
    _ = due_at
    rows = await list_care_tasks(user_id=user_id, include_terminal=False, limit=50)
    out: list[dict[str, Any]] = []
    target = identity_key(title, task_type)
    for row in rows:
        if row.get("status") not in ACTIVE_STATUSES:
            continue
        if (row.get("task_type") or task_type) != task_type:
            continue
        # Exact identity already handled by reuse path
        if identity_key(row["title"], task_type) == target:
            continue
        overlap = _token_overlap(title, row["title"])
        if overlap >= threshold:
            out.append(row)
    return out


async def _linked_reminder_schedule_type(
    *,
    user_id: str,
    reminder_id: str | None,
) -> str | None:
    """Return Reminder.schedule_type for a CareTask-linked reminder, if any."""
    if not reminder_id:
        return None
    from app.db.models import Reminder
    from app.db.session import async_session

    try:
        rid = uuid.UUID(str(reminder_id))
    except (ValueError, TypeError):
        return None
    db_user_id = normalize_user_id(user_id)
    async with async_session() as db:
        rem = await db.get(Reminder, rid)
        if rem is None or rem.user_id != db_user_id:
            return None
        return rem.schedule_type


async def _update_task_schedule(
    *,
    user_id: str,
    task_id: str,
    due_at: datetime,
    title: str | None = None,
    schedule_type: str = "once",
) -> dict[str, Any]:
    """Attach / refresh due_at (+ reminder) on an existing active CareTask."""
    from app.db.models import Reminder
    from app.db.session import async_session

    st = schedule_type if schedule_type in {"daily", "once", "weekly", "interval"} else "once"
    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    async with async_session() as db:
        row = await _get_task(db, db_user_id, task_id)
        if title and normalize_title(title) == normalize_title(row.title):
            # Prefer shorter/cleaner display title when identity matches
            if len(title.strip()) < len((row.title or "").strip()):
                row.title = title.strip()
        row.due_at = due_at
        row.status = infer_initial_status(due_at, now)
        row.updated_at = now
        if row.reminder_id:
            rem = await db.get(Reminder, row.reminder_id)
            if rem is not None:
                rem.time_of_day = due_at
                rem.next_fire_at = due_at
                rem.is_active = True
                rem.title = row.title
                rem.schedule_type = st
        else:
            reminder = Reminder(
                user_id=db_user_id,
                title=row.title,
                description=row.notes or f"caretask:{row.task_type}",
                schedule_type=st,
                time_of_day=due_at,
                next_fire_at=due_at,
                is_active=True,
                created_by=row.created_by or "chat",
            )
            db.add(reminder)
            await db.flush()
            row.reminder_id = reminder.id
        await db.commit()
        await db.refresh(row)
        data = task_to_dict(row)
        data["schedule_type"] = st
        return data

def _title_matches_hint(hint: str, title: str) -> bool:
    nt = normalize_title(title)
    nh = normalize_title(hint)
    if not nh or not nt:
        return False
    return nh in nt or nt in nh or _token_overlap(nh, nt) >= 0.55


async def resolve_task_ref(
    *,
    user_id: str,
    task_id: str | None = None,
    title_hint: str | None = None,
    query: str | None = None,
) -> ResolveResult:
    """Resolve a mutate referent: 0→none, 1→one, ≥2→many (no silent pick).

    Category-level cancel/complete (「取消吃药提醒」) with ≥2 active tasks
    always returns ``many`` — never bind to a single generic 「吃药」 title.

    Specific medicine tokens (「降压药我吃过了」) must NOT broaden to unrelated
    active tasks when zero pending matches — return ``none`` (optionally
    ``already_done`` when a terminal task matches the same token).
    """
    if not task_id:
        task_id = extract_task_id_from_query(query)

    if task_id:
        rows = await list_care_tasks(user_id=user_id, include_terminal=False, limit=50)
        for row in rows:
            if row["id"] == str(task_id):
                return ResolveResult(kind="one", task=row)
        # Allow resolving terminal by id via direct get path later; treat as none for active
        return ResolveResult(kind="none")

    rows = await list_care_tasks(user_id=user_id, include_terminal=False, limit=50)
    active = [r for r in rows if r.get("status") in ACTIVE_STATUSES]
    hint = extract_resolve_hint(title_hint, query)

    # No clear referent / category-level med phrasing → clarify when ≥2.
    if not hint or is_generic_med_hint(hint):
        if len(active) == 0:
            return ResolveResult(kind="none", hint=hint or None)
        if len(active) == 1:
            return ResolveResult(kind="one", task=active[0], hint=hint or None)
        return ResolveResult(kind="many", candidates=active, hint=hint or None)

    matched = [r for r in active if _title_matches_hint(hint, r["title"])]
    if len(matched) == 1:
        return ResolveResult(kind="one", task=matched[0], hint=hint)
    if len(matched) >= 2:
        return ResolveResult(kind="many", candidates=matched, hint=hint)

    # Specific referent matched no pending task — never offer unrelated meds.
    terminal_rows = await list_care_tasks(user_id=user_id, include_terminal=True, limit=50)
    done_match = [
        r
        for r in terminal_rows
        if r.get("status") == "done" and _title_matches_hint(hint, r["title"])
    ]
    return ResolveResult(
        kind="none",
        hint=hint,
        already_done=bool(done_match),
        candidates=done_match[:3] if done_match else None,
    )


async def create_care_task(
    *,
    user_id: str,
    title: str,
    task_type: str = "medication",
    due_at: datetime | None = None,
    notes: str | None = None,
    created_by: str = "chat",
    link_reminder: bool = True,
    schedule_type: str | None = None,
    query: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Create or reuse an active CareTask with the same identity.

    Identity = task_type + normalized title (schedule ignored). Same med must
    never silent-double-create. If a clearer ``due_at`` arrives on reuse, update
    the existing task schedule.

    Reminder projection uses ``schedule_type`` (daily/once) inferred from
    ``query`` when not provided — 「每天晚上8点吃降压药」 must not store once.

    Returns task dict plus optional ``_action``:
    ``caretask_create`` | ``caretask_reuse`` | ``caretask_clarify_create``.
    """
    title = (title or "").strip() or "吃药"
    st = schedule_type or infer_schedule_type_from_utterance(query or title)
    if st not in {"daily", "once", "weekly", "interval"}:
        st = "once"
    existing = await find_active_by_fingerprint(
        user_id=user_id, title=title, task_type=task_type, due_at=due_at
    )
    if existing is not None:
        existing_due = _parse_row_due(existing)
        existing_st = await _linked_reminder_schedule_type(
            user_id=user_id, reminder_id=existing.get("reminder_id")
        )
        due_changed = due_at is not None and (
            existing_due is None or existing_due != due_at
        )
        # once→daily (same clock) must still refresh Reminder + device projection.
        # Missing linked schedule is treated as once for comparison.
        schedule_type_changed = (existing_st or "once") != st
        needs_schedule_refresh = due_changed or (
            schedule_type_changed and (due_at is not None or existing_due is not None)
        )
        if needs_schedule_refresh:
            refresh_due = due_at or existing_due
            if refresh_due is not None:
                try:
                    updated = await _update_task_schedule(
                        user_id=user_id,
                        task_id=str(existing["id"]),
                        due_at=refresh_due,
                        title=title,
                        schedule_type=st,
                    )
                    updated["_action"] = "caretask_reuse"
                    updated["_schedule_updated"] = True
                    return updated
                except Exception as e:
                    logger.warning("CareTask schedule update on reuse failed: %s", e)
        data = dict(existing)
        data["_action"] = "caretask_reuse"
        data["_schedule_updated"] = False
        data["schedule_type"] = existing_st or st
        return data

    near = await find_near_duplicate_candidates(
        user_id=user_id, title=title, task_type=task_type, due_at=due_at
    )
    if near:
        return {
            "_action": "caretask_clarify_create",
            "candidates": near,
            "proposed": {
                "title": title,
                "task_type": task_type,
                "due_at": due_at.isoformat() if due_at else None,
                "schedule_type": st,
            },
        }

    from app.db.models import CareTask, Reminder
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    status = infer_initial_status(due_at, now)
    reminder_id: uuid.UUID | None = None

    async with async_session() as db:
        if link_reminder and due_at is not None:
            reminder = Reminder(
                user_id=db_user_id,
                title=title,
                description=notes or f"caretask:{task_type}",
                schedule_type=st,
                time_of_day=due_at,
                next_fire_at=due_at,
                is_active=True,
                created_by=created_by,
            )
            db.add(reminder)
            await db.flush()
            reminder_id = reminder.id

        row = CareTask(
            user_id=db_user_id,
            title=title,
            task_type=task_type,
            status=status,
            due_at=due_at,
            reminder_id=reminder_id,
            notes=notes,
            created_by=created_by,
            idempotency_key=idempotency_key,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        data = task_to_dict(row)
        data["_action"] = "caretask_create"
        data["schedule_type"] = st
        return data


async def list_care_tasks(
    *,
    user_id: str,
    include_terminal: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.db.models import CareTask
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    async with async_session() as db:
        stmt = select(CareTask).where(CareTask.user_id == db_user_id)
        if not include_terminal:
            stmt = stmt.where(CareTask.status.in_(list(ACTIVE_STATUSES | {"missed"})))
        stmt = stmt.order_by(CareTask.due_at.asc().nullslast(), CareTask.created_at.desc()).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()
        out: list[dict[str, Any]] = []
        dirty = False
        for row in rows:
            new_status = refresh_status(row.status, row.due_at, row.snooze_until, now)
            if new_status != row.status and can_transition(row.status, new_status):
                row.status = new_status
                row.updated_at = now
                dirty = True
            out.append(task_to_dict(row))
        if dirty:
            await db.commit()
        return out


async def _get_task(db: Any, user_id: uuid.UUID, task_id: str) -> Any:
    from sqlalchemy import select

    from app.db.models import CareTask

    row = (
        await db.execute(
            select(CareTask).where(
                CareTask.id == uuid.UUID(task_id),
                CareTask.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError("care_task_not_found")
    return row


async def _get_versioned_task_for_update(
    db: Any,
    user_id: uuid.UUID,
    task_id: str,
    expected_version: int | None,
) -> Any:
    from sqlalchemy import select

    from app.db.models import CareTask

    if expected_version is None:
        return await _get_task(db, user_id, task_id)

    task_uuid = uuid.UUID(task_id)
    row = (
        await db.execute(
            select(CareTask)
            .where(
                CareTask.id == task_uuid,
                CareTask.user_id == user_id,
                CareTask.version == expected_version,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is not None:
        return row

    current = (
        await db.execute(
            select(CareTask.version).where(CareTask.id == task_uuid, CareTask.user_id == user_id)
        )
    ).scalar_one_or_none()
    if current is None:
        raise LookupError("care_task_not_found")
    raise StaleCareTaskVersionError(
        expected_version=expected_version,
        current_version=current or 1,
    )


async def update_care_task(
    *,
    user_id: str,
    task_id: str,
    expected_version: int,
    title: str | None = None,
    due_at: datetime | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    from app.db.models import Reminder
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    async with async_session() as db:
        row = await _get_versioned_task_for_update(db, db_user_id, task_id, expected_version)
        if title is not None:
            row.title = title.strip() or row.title
        if notes is not None:
            row.notes = notes
        if due_at is not None:
            row.due_at = due_at
            row.status = infer_initial_status(due_at, now)
            if row.reminder_id:
                reminder = await db.get(Reminder, row.reminder_id)
                if reminder is not None:
                    reminder.title = row.title
                    reminder.time_of_day = due_at
                    reminder.next_fire_at = due_at
                    reminder.is_active = True
        row.version = (row.version or 1) + 1
        row.updated_at = now
        await db.commit()
        await db.refresh(row)
        return task_to_dict(row)


async def complete_care_task(
    *,
    user_id: str,
    task_id: str,
    expected_version: int | None = None,
) -> dict[str, Any]:
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    async with async_session() as db:
        row = await _get_versioned_task_for_update(db, db_user_id, task_id, expected_version)
        current = refresh_status(row.status, row.due_at, row.snooze_until, now)
        if current != row.status and can_transition(row.status, current):
            row.status = current
        assert_transition(row.status, "done")
        row.status = "done"
        row.completed_at = now
        row.updated_at = now
        row.version = (getattr(row, "version", 1) or 1) + 1
        row.snooze_until = None
        if row.reminder_id:
            from app.db.models import Reminder

            rem = await db.get(Reminder, row.reminder_id)
            if rem is not None:
                rem.is_active = False
        await db.commit()
        await db.refresh(row)
        return task_to_dict(row)


async def snooze_care_task(
    *,
    user_id: str,
    task_id: str | None = None,
    minutes: int = 30,
    expected_version: int | None = None,
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.models import CareTask, Reminder
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    minutes = max(1, min(int(minutes), 24 * 60))
    now = datetime.utcnow()
    snooze_until = now + timedelta(minutes=minutes)

    async with async_session() as db:
        if task_id:
            row = await _get_versioned_task_for_update(db, db_user_id, task_id, expected_version)
        else:
            row = (
                await db.execute(
                    select(CareTask)
                    .where(
                        CareTask.user_id == db_user_id,
                        CareTask.status.in_(list(ACTIVE_STATUSES)),
                    )
                    .order_by(CareTask.due_at.asc().nullslast(), CareTask.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                raise LookupError("no_active_care_task")

        current = refresh_status(row.status, row.due_at, row.snooze_until, now)
        if current != row.status and can_transition(row.status, current):
            row.status = current
        assert_transition(row.status, "snoozed")
        row.status = "snoozed"
        row.snooze_until = snooze_until
        row.due_at = snooze_until
        row.updated_at = now
        row.version = (getattr(row, "version", 1) or 1) + 1
        if row.reminder_id:
            rem = await db.get(Reminder, row.reminder_id)
            if rem is not None:
                rem.next_fire_at = snooze_until
                rem.is_active = True
        await db.commit()
        await db.refresh(row)
        data = task_to_dict(row)
        data["snooze_minutes"] = minutes
        return data


async def cancel_care_task(
    *,
    user_id: str,
    task_id: str,
    expected_version: int | None = None,
) -> dict[str, Any]:
    from app.db.models import Reminder
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    async with async_session() as db:
        row = await _get_versioned_task_for_update(db, db_user_id, task_id, expected_version)
        assert_transition(row.status, "cancelled")
        row.status = "cancelled"
        row.updated_at = now
        row.version = (getattr(row, "version", 1) or 1) + 1
        row.snooze_until = None
        if row.reminder_id:
            rem = await db.get(Reminder, row.reminder_id)
            if rem is not None:
                rem.is_active = False
        await db.commit()
        await db.refresh(row)
        return task_to_dict(row)


async def mark_missed(*, user_id: str, task_id: str) -> dict[str, Any]:
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    async with async_session() as db:
        row = await _get_task(db, db_user_id, task_id)
        current = refresh_status(row.status, row.due_at, row.snooze_until, now)
        if current != row.status and can_transition(row.status, current):
            row.status = current
        assert_transition(row.status, "missed")
        row.status = "missed"
        row.updated_at = now
        row.version = (getattr(row, "version", 1) or 1) + 1
        await db.commit()
        await db.refresh(row)
        return task_to_dict(row)
