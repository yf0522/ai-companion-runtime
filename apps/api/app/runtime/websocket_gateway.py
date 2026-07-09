import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

from app.runtime import session_service

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

    async def connect(
        self, websocket: WebSocket, user_id: str, session_id: Optional[str] = None
    ) -> Connection:
        session_id = await session_service.ensure_session(user_id, session_id)
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
            asyncio.create_task(
                session_service.increment_message_count(conn.session_id)
            )
        except Exception as e:
            logger.error(f"Harness error: {e}", exc_info=True)
            await stream_mgr.send_error("harness_error", str(e), retry=True)
        finally:
            conn.is_generating = False

    async def stop_generation(self, conn: Connection, trace_id: str):
        if conn.is_generating:
            conn.cancel_event.set()
