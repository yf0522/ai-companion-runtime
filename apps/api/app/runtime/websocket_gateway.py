import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

from app.runtime import session_service
from app.runtime.agent_runtime import DEFAULT_RUNTIME, get_agent_runtime
from app.runtime.stream_manager import StreamManager

logger = logging.getLogger(__name__)
_CANCEL_CLEANUP_GRACE_S = 0.5


@dataclass
class Connection:
    websocket: WebSocket
    user_id: str
    session_id: str
    agent_runtime: str = DEFAULT_RUNTIME
    last_message_id: Optional[str] = None
    is_generating: bool = False
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    active_trace_id: Optional[str] = None
    active_message_task: asyncio.Task | None = field(default=None, repr=False)


class _ConnectionStreamManager(StreamManager):
    """Bind the trace emitted by a runtime to its active connection turn."""

    def __init__(self, websocket: WebSocket, conn: Connection):
        super().__init__(websocket)
        self._conn = conn

    async def send_trace(self, trace_id: str):
        self._conn.active_trace_id = trace_id
        await super().send_trace(trace_id)


class WebSocketGateway:
    def __init__(self):
        self._connections: dict[str, Connection] = {}  # session_id -> Connection

    async def connect(
        self,
        websocket: WebSocket,
        user_id: str,
        session_id: Optional[str] = None,
        agent_runtime: str = DEFAULT_RUNTIME,
    ) -> Connection:
        session_id = await session_service.ensure_session(user_id, session_id)
        conn = Connection(
            websocket=websocket,
            user_id=user_id,
            session_id=session_id,
            agent_runtime=agent_runtime,
        )
        self._connections[session_id] = conn
        logger.info(
            "Connected: user=%s session=%s runtime=%s",
            user_id,
            session_id,
            agent_runtime,
        )
        return conn

    async def disconnect(self, conn: Connection):
        self._connections.pop(conn.session_id, None)
        logger.info(f"Disconnected: session={conn.session_id}")

    async def handle_message(self, conn: Connection, message: str):
        """Main message handling pipeline — dispatches to selected AgentRuntime."""
        current_task = asyncio.current_task()
        conn.active_message_task = current_task
        conn.active_trace_id = None
        if not conn.is_generating:
            conn.cancel_event.clear()
            conn.is_generating = True
        stream_mgr = _ConnectionStreamManager(conn.websocket, conn)
        runtime = get_agent_runtime(conn.agent_runtime)

        try:
            result = await runtime.run(
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
        except Exception as exc:
            logger.error(
                "Agent runtime failed runtime=%s error_class=%s code=runtime_error",
                conn.agent_runtime,
                type(exc).__name__,
            )
            await stream_mgr.send_error(
                "runtime_error",
                "服务暂时不可用，请稍后再试。",
                retry=True,
            )
        finally:
            if conn.active_message_task is current_task:
                conn.is_generating = False
                conn.active_trace_id = None
                conn.active_message_task = None

    async def stop_generation(self, conn: Connection, trace_id: str) -> bool:
        requested_trace_id = trace_id.strip()
        if (
            not requested_trace_id
            or not conn.is_generating
            or conn.active_trace_id != requested_trace_id
        ):
            return False

        conn.cancel_event.set()
        task = conn.active_message_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(task, return_exceptions=True),
                    timeout=_CANCEL_CLEANUP_GRACE_S,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Turn cleanup exceeded grace trace=%s code=cancel_cleanup_timeout",
                    requested_trace_id[:80],
                )
        await StreamManager(conn.websocket).send_cancelled(requested_trace_id)
        return True
