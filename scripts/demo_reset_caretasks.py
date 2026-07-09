#!/usr/bin/env python3
"""Cancel pending CareTasks for a demo user (scoped; never blind prod wipe).

Usage:
  # Dry-run (default): show what would be cancelled
  python scripts/demo_reset_caretasks.py --user demo_elder

  # Apply: cancel active pending/due/snoozed tasks for demo_elder
  python scripts/demo_reset_caretasks.py --user demo_elder --apply

  # Also deactivate linked reminders
  python scripts/demo_reset_caretasks.py --user demo_elder --apply --reminders

Requires DATABASE_URL (asyncpg) from env / .env.
Only usernames matching demo_* (or --force) are allowed.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path


def _load_dotenv() -> None:
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def _normalize_user_id(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except (ValueError, AttributeError, TypeError):
        return uuid.uuid5(uuid.NAMESPACE_DNS, str(user_id))


ACTIVE = ("pending", "due", "snoozed")


async def _run(*, username: str, apply: bool, reminders: bool, force: bool) -> int:
    if not force and not username.startswith("demo_"):
        print(
            f"Refusing non-demo user '{username}'. "
            "Pass --force only if you intentionally target this account.",
            file=sys.stderr,
        )
        return 2

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    # Prefer sync-friendly URL for asyncpg via SQLAlchemy async engine already in app.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

    from sqlalchemy import select, update

    from app.db.models import CareTask, Reminder, User
    from app.db.session import async_session

    async with async_session() as db:
        user = (
            await db.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if user is None:
            # Fall back to uuid5 of username (auth may store that way)
            uid = _normalize_user_id(username)
            user = await db.get(User, uid)
        if user is None:
            print(f"User not found: {username}", file=sys.stderr)
            return 1

        rows = (
            await db.execute(
                select(CareTask).where(
                    CareTask.user_id == user.id,
                    CareTask.status.in_(list(ACTIVE)),
                )
            )
        ).scalars().all()

        print(f"user={username} id={user.id} active_care_tasks={len(rows)}")
        for row in rows:
            due = row.due_at.isoformat() if row.due_at else "-"
            print(f"  - {row.id} | {row.title} | {row.status} | due={due}")

        if not rows:
            print("nothing_to_cancel")
            return 0

        if not apply:
            print("dry_run: pass --apply to cancel these tasks")
            return 0

        from datetime import datetime

        now = datetime.utcnow()
        reminder_ids = [r.reminder_id for r in rows if r.reminder_id]
        for row in rows:
            row.status = "cancelled"
            row.updated_at = now
            row.snooze_until = None
        if reminders and reminder_ids:
            await db.execute(
                update(Reminder)
                .where(Reminder.id.in_(reminder_ids))
                .values(is_active=False)
            )
            print(f"deactivated_reminders={len(reminder_ids)}")
        await db.commit()
        print(f"cancelled={len(rows)}")
        return 0


def main() -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Reset demo CareTasks (scoped)")
    parser.add_argument("--user", default="demo_elder", help="Username (default demo_elder)")
    parser.add_argument("--apply", action="store_true", help="Actually cancel tasks")
    parser.add_argument(
        "--reminders",
        action="store_true",
        help="Also deactivate linked reminders",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow non-demo_* usernames (dangerous)",
    )
    args = parser.parse_args()
    return asyncio.run(
        _run(
            username=args.user,
            apply=args.apply,
            reminders=args.reminders,
            force=args.force,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
