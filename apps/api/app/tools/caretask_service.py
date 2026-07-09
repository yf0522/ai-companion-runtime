"""CareTask domain: state machine + persistence. Reminder = scheduling projection."""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

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
        "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
    }


def normalize_title(title: str) -> str:
    """Normalize CareTask title for fingerprint / near-dup matching."""
    text = (title or "").strip()
    text = _WHITESPACE.sub("", text)
    text = _TITLE_NOISE.sub("", text)
    text = _TITLE_TRAIL.sub("", text)
    # Strip common create prefixes / filler that survive inference
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
    text = text.lower()
    return text.strip() or (title or "").strip()[:80]


def due_bucket(due_at: datetime | None) -> str | None:
    if due_at is None:
        return None
    return due_at.strftime("%Y-%m-%d")


def title_fingerprint(title: str, task_type: str, due_at: datetime | None = None) -> str:
    return f"{task_type}|{normalize_title(title)}|{due_bucket(due_at) or 'undated'}"


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


@dataclass
class ResolveResult:
    kind: Literal["one", "many", "none"]
    task: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] | None = None


async def find_active_by_fingerprint(
    *,
    user_id: str,
    title: str,
    task_type: str,
    due_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Exact active fingerprint match (same type + normalized title + due day)."""
    rows = await list_care_tasks(user_id=user_id, include_terminal=False, limit=50)
    target = title_fingerprint(title, task_type, due_at)
    for row in rows:
        if row.get("status") not in ACTIVE_STATUSES:
            continue
        row_due = None
        if row.get("due_at"):
            try:
                row_due = datetime.fromisoformat(str(row["due_at"]).replace("Z", "+00:00")).replace(
                    tzinfo=None
                )
            except ValueError:
                row_due = None
        if title_fingerprint(row["title"], row.get("task_type") or task_type, row_due) == target:
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
    """Near-dup active tasks with different due buckets (clarify before create)."""
    rows = await list_care_tasks(user_id=user_id, include_terminal=False, limit=50)
    out: list[dict[str, Any]] = []
    new_bucket = due_bucket(due_at)
    for row in rows:
        if row.get("status") not in ACTIVE_STATUSES:
            continue
        if (row.get("task_type") or task_type) != task_type:
            continue
        row_due = None
        if row.get("due_at"):
            try:
                row_due = datetime.fromisoformat(str(row["due_at"]).replace("Z", "+00:00")).replace(
                    tzinfo=None
                )
            except ValueError:
                row_due = None
        # Exact fingerprint already handled by reuse path
        if title_fingerprint(row["title"], task_type, row_due) == title_fingerprint(
            title, task_type, due_at
        ):
            continue
        overlap = _token_overlap(title, row["title"])
        if overlap < threshold:
            continue
        # Same title-ish but different due day → clarify
        if due_bucket(row_due) != new_bucket or normalize_title(title) != normalize_title(
            row["title"]
        ):
            if overlap >= threshold:
                out.append(row)
    return out


async def resolve_task_ref(
    *,
    user_id: str,
    task_id: str | None = None,
    title_hint: str | None = None,
    query: str | None = None,
) -> ResolveResult:
    """Resolve a mutate referent: 0→none, 1→one, ≥2→many (no silent limit=1)."""
    if task_id:
        rows = await list_care_tasks(user_id=user_id, include_terminal=False, limit=50)
        for row in rows:
            if row["id"] == str(task_id):
                return ResolveResult(kind="one", task=row)
        # Allow resolving terminal by id via direct get path later; treat as none for active
        return ResolveResult(kind="none")

    rows = await list_care_tasks(user_id=user_id, include_terminal=False, limit=50)
    active = [r for r in rows if r.get("status") in ACTIVE_STATUSES]
    hint = normalize_title(title_hint or query or "")
    if hint:
        matched = [
            r
            for r in active
            if hint in normalize_title(r["title"])
            or normalize_title(r["title"]) in hint
            or _token_overlap(hint, r["title"]) >= 0.55
        ]
        if len(matched) == 1:
            return ResolveResult(kind="one", task=matched[0])
        if len(matched) >= 2:
            return ResolveResult(kind="many", candidates=matched)
        if not matched and len(active) == 0:
            return ResolveResult(kind="none")
        if not matched and len(active) == 1:
            return ResolveResult(kind="one", task=active[0])
        if not matched and len(active) >= 2:
            return ResolveResult(kind="many", candidates=active)
        return ResolveResult(kind="none")

    if len(active) == 0:
        return ResolveResult(kind="none")
    if len(active) == 1:
        return ResolveResult(kind="one", task=active[0])
    return ResolveResult(kind="many", candidates=active)


async def create_care_task(
    *,
    user_id: str,
    title: str,
    task_type: str = "medication",
    due_at: datetime | None = None,
    notes: str | None = None,
    created_by: str = "chat",
    link_reminder: bool = True,
) -> dict[str, Any]:
    """Create or reuse an active CareTask with the same fingerprint.

    Returns task dict plus optional ``_action``:
    ``caretask_create`` | ``caretask_reuse`` | ``caretask_clarify_create``.
    """
    from app.db.models import CareTask, Reminder
    from app.db.session import async_session

    title = (title or "").strip() or "吃药"
    existing = await find_active_by_fingerprint(
        user_id=user_id, title=title, task_type=task_type, due_at=due_at
    )
    if existing is not None:
        data = dict(existing)
        data["_action"] = "caretask_reuse"
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
            },
        }

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
                schedule_type="once",
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
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        data = task_to_dict(row)
        data["_action"] = "caretask_create"
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


async def complete_care_task(*, user_id: str, task_id: str) -> dict[str, Any]:
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    async with async_session() as db:
        row = await _get_task(db, db_user_id, task_id)
        current = refresh_status(row.status, row.due_at, row.snooze_until, now)
        if current != row.status and can_transition(row.status, current):
            row.status = current
        assert_transition(row.status, "done")
        row.status = "done"
        row.completed_at = now
        row.updated_at = now
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
            row = await _get_task(db, db_user_id, task_id)
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


async def cancel_care_task(*, user_id: str, task_id: str) -> dict[str, Any]:
    from app.db.models import Reminder
    from app.db.session import async_session

    db_user_id = normalize_user_id(user_id)
    now = datetime.utcnow()
    async with async_session() as db:
        row = await _get_task(db, db_user_id, task_id)
        assert_transition(row.status, "cancelled")
        row.status = "cancelled"
        row.updated_at = now
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
        await db.commit()
        await db.refresh(row)
        return task_to_dict(row)
