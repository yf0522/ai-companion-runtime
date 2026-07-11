"""Shared DB session helpers for browser WS and device realtime paths."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class SessionPersistenceError(RuntimeError):
    """A durable session could not be created."""


async def create_session(user_id: str) -> str:
    """Create a new session row and return its UUID string.

    Development may opt into an explicit ephemeral session. Production must
    never imply durable ownership or audit after a failed database write.
    """
    from app.db.session import async_session
    from app.db.models import Session as SessionModel

    session_id = str(uuid.uuid4())
    try:
        user_uuid = uuid.UUID(user_id)
    except (ValueError, AttributeError):
        user_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, user_id)

    try:
        async with async_session() as db:
            db_session = SessionModel(
                id=uuid.UUID(session_id),
                user_id=user_uuid,
                status="active",
                message_count=0,
            )
            db.add(db_session)
            await db.commit()
        return session_id
    except Exception as e:
        from app.config.settings import settings

        if settings.app_env.lower() != "production" and settings.allow_ephemeral_sessions:
            logger.warning("Session DB create failed; using explicit development fallback: %s", e)
            return session_id
        raise SessionPersistenceError("Failed to persist session") from e


async def get_session_owner(session_id: str) -> Optional[str]:
    try:
        from app.db.session import async_session
        from app.db.models import Session as SessionModel
        from sqlalchemy import select

        async with async_session() as db:
            result = await db.execute(
                select(SessionModel.user_id).where(
                    SessionModel.id == uuid.UUID(session_id)
                )
            )
            row = result.scalar_one_or_none()
            return str(row) if row else None
    except (ValueError, Exception) as e:
        logger.debug(f"Session lookup failed for {session_id}: {e}")
        return None


async def ensure_session(user_id: str, session_id: str | None = None) -> str:
    if session_id:
        owner = await get_session_owner(session_id)
        if owner is None:
            logger.warning(
                f"Client provided unknown session_id={session_id}, creating new"
            )
        elif owner != user_id and owner != str(
            uuid.uuid5(uuid.NAMESPACE_DNS, user_id)
        ):
            # Allow deterministic uuid5 mapping used by Pi runtime for non-UUID subs
            try:
                if owner != str(uuid.UUID(user_id)):
                    logger.warning(
                        f"Session ownership mismatch: session={session_id} "
                        f"belongs to user={owner}, requested by user={user_id}."
                    )
                    session_id = None
            except ValueError:
                logger.warning(
                    f"Session ownership mismatch: session={session_id} "
                    f"belongs to user={owner}, requested by user={user_id}."
                )
                session_id = None
        else:
            await touch_session(session_id)
            return session_id

    new_id = await create_session(user_id)
    await touch_session(new_id)
    return new_id


async def touch_session(session_id: str) -> None:
    try:
        from app.db.session import async_session
        from app.db.models import Session as SessionModel
        from sqlalchemy import update

        async with async_session() as db:
            await db.execute(
                update(SessionModel)
                .where(SessionModel.id == uuid.UUID(session_id))
                .values(last_active_at=datetime.utcnow())
            )
            await db.commit()
    except Exception as e:
        logger.debug(f"Failed to touch session {session_id}: {e}")


async def increment_message_count(session_id: str) -> None:
    try:
        from app.db.session import async_session
        from app.db.models import Session as SessionModel
        from sqlalchemy import update

        async with async_session() as db:
            await db.execute(
                update(SessionModel)
                .where(SessionModel.id == uuid.UUID(session_id))
                .values(
                    message_count=SessionModel.message_count + 1,
                    last_active_at=datetime.utcnow(),
                )
            )
            await db.commit()
    except Exception as e:
        logger.debug(f"Failed to increment message count for {session_id}: {e}")
