import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class Connection:
    websocket: WebSocket
    user_id: str
    session_id: str
    last_message_id: Optional[str] = None
    is_generating: bool = False
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


class WebSocketGateway:
    def __init__(self):
        self._connections: dict[str, Connection] = {}  # session_id -> Connection

    async def connect(self, websocket: WebSocket, user_id: str, session_id: Optional[str] = None) -> Connection:
        # If client provides a session_id, validate ownership against DB
        if session_id:
            owner = await self._get_session_owner(session_id)
            if owner is None:
                # Session doesn't exist in DB — ignore client-provided id
                logger.warning(f"Client provided unknown session_id={session_id}, creating new")
                session_id = None
            elif owner != user_id:
                # Session belongs to a different user
                logger.warning(
                    f"Session ownership mismatch: session={session_id} "
                    f"belongs to user={owner}, requested by user={user_id}. "
                    f"Creating new session."
                )
                session_id = None

        if not session_id:
            session_id = await self._create_db_session(user_id)

        # Update last_active_at
        await self._touch_session(session_id)

        conn = Connection(
            websocket=websocket,
            user_id=user_id,
            session_id=session_id,
        )
        self._connections[session_id] = conn
        logger.info(f"Connected: user={user_id} session={session_id}")
        return conn

    async def disconnect(self, conn: Connection):
        self._connections.pop(conn.session_id, None)
        logger.info(f"Disconnected: session={conn.session_id}")

    async def handle_message(self, conn: Connection, message: str):
        """Main message handling pipeline — uses Agent Harness."""
        from app.runtime.agent_harness import AgentHarness
        from app.runtime.stream_manager import StreamManager

        conn.is_generating = True
        conn.cancel_event.clear()
        stream_mgr = StreamManager(conn.websocket)
        harness = AgentHarness()

        try:
            result = await harness.run(
                user_id=conn.user_id,
                session_id=conn.session_id,
                message=message,
                stream_mgr=stream_mgr,
                cancel_event=conn.cancel_event,
            )
            if result.get("message_id"):
                conn.last_message_id = result["message_id"]
            # Increment session message count (fire-and-forget)
            asyncio.create_task(self._increment_message_count(conn.session_id))
        except Exception as e:
            logger.error(f"Harness error: {e}", exc_info=True)
            await stream_mgr.send_error("harness_error", str(e), retry=True)
        finally:
            conn.is_generating = False

    async def stop_generation(self, conn: Connection, trace_id: str):
        if conn.is_generating:
            conn.cancel_event.set()

    # --- DB session helpers ---

    async def _create_db_session(self, user_id: str) -> str:
        """Create a new session row in the DB and return its UUID string.

        Raises RuntimeError if DB insertion fails — caller should close the WS.
        """
        from app.db.session import async_session
        from app.db.models import Session as SessionModel

        session_id = str(uuid.uuid4())
        try:
            async with async_session() as db:
                db_session = SessionModel(
                    id=uuid.UUID(session_id),
                    user_id=uuid.UUID(user_id),
                    status="active",
                    message_count=0,
                )
                db.add(db_session)
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to create DB session: {e}")
            raise RuntimeError(f"Session creation failed: {e}")
        return session_id

    async def _get_session_owner(self, session_id: str) -> Optional[str]:
        """Look up the owner user_id of a session from DB. Returns None if not found."""
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

    async def _touch_session(self, session_id: str):
        """Update last_active_at for a session."""
        try:
            from app.db.session import async_session
            from app.db.models import Session as SessionModel
            from sqlalchemy import update
            from datetime import datetime

            async with async_session() as db:
                await db.execute(
                    update(SessionModel)
                    .where(SessionModel.id == uuid.UUID(session_id))
                    .values(last_active_at=datetime.utcnow())
                )
                await db.commit()
        except Exception as e:
            logger.debug(f"Failed to touch session {session_id}: {e}")

    async def _increment_message_count(self, session_id: str):
        """Increment message_count for a session."""
        try:
            from app.db.session import async_session
            from app.db.models import Session as SessionModel
            from sqlalchemy import update
            from datetime import datetime

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
