"""Durable PostgreSQL transcript evidence with concurrency-safe ordering."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import Message, Session
from app.db.session import async_session


@dataclass(frozen=True)
class PersistedTurn:
    user_message_id: str
    assistant_message_id: str
    user_message_index: int
    assistant_message_index: int


async def persist_turn_messages(
    *,
    session_id: str,
    user_id: str,
    trace_id: str,
    user_content: str,
    assistant_content: str,
    user_message_id: str | None = None,
    assistant_message_id: str | None = None,
) -> PersistedTurn:
    """Append an owned user/assistant pair, retrying one ordering race."""
    session_uuid = uuid.UUID(str(session_id))
    user_uuid = uuid.UUID(str(user_id))
    explicit_user_id = uuid.UUID(str(user_message_id)) if user_message_id else None
    explicit_assistant_id = (
        uuid.UUID(str(assistant_message_id)) if assistant_message_id else None
    )
    if explicit_user_id is not None and explicit_user_id == explicit_assistant_id:
        raise ValueError("user and assistant message IDs must differ")
    last_error: IntegrityError | None = None
    for _attempt in range(2):
        try:
            async with async_session() as db:
                async with db.begin():
                    parent = await db.scalar(
                        select(Session).where(Session.id == session_uuid).with_for_update()
                    )
                    if parent is None:
                        raise LookupError(f"session not found: {session_id}")
                    if parent.user_id != user_uuid:
                        raise PermissionError("session does not belong to user")
                    current = await db.scalar(
                        select(func.coalesce(func.max(Message.message_index), -1)).where(
                            Message.session_id == session_uuid
                        )
                    )
                    first_index = int(current) + 1
                    user_message = Message(
                        id=explicit_user_id,
                        session_id=session_uuid,
                        user_id=user_uuid,
                        role="user",
                        content=user_content,
                        message_index=first_index,
                        trace_id=trace_id,
                    )
                    assistant_message = Message(
                        id=explicit_assistant_id,
                        session_id=session_uuid,
                        user_id=user_uuid,
                        role="assistant",
                        content=assistant_content,
                        message_index=first_index + 1,
                        trace_id=trace_id,
                    )
                    db.add_all([user_message, assistant_message])
                    await db.flush()
                    result = PersistedTurn(
                        user_message_id=str(user_message.id),
                        assistant_message_id=str(assistant_message.id),
                        user_message_index=first_index,
                        assistant_message_index=first_index + 1,
                    )
                return result
        except IntegrityError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error
