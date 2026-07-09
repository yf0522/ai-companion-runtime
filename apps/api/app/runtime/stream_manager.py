import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class StreamManager:
    """Manages sending structured WebSocket messages to the client.

    Tracks connection health via `dead` — when a send fails, the connection
    is marked dead so the harness can abort streaming instead of generating
    tokens into the void.
    """

    def __init__(self, websocket: WebSocket):
        self._ws = websocket
        self._dead = False

    @property
    def dead(self) -> bool:
        """True after the first send failure — the WebSocket is unreachable."""
        return self._dead

    async def send_trace(self, trace_id: str):
        await self._send({"type": "trace", "trace_id": trace_id})

    async def send_first_reply(self, text: str, ttft_ms: int):
        await self._send({"type": "first_reply", "text": text, "ttft_ms": ttft_ms})

    async def send_delta(self, text: str):
        await self._send({"type": "delta", "text": text})

    async def send_tool_status(self, tool: str, status: str):
        await self._send({"type": "tool_status", "tool": tool, "status": status})

    async def send_tool_result(self, tool: str, text: str):
        await self._send({"type": "tool_result", "tool": tool, "text": text})

    async def send_risk_alert(self, level: str, message: str):
        await self._send({"type": "risk_alert", "level": level, "message": message})

    async def send_reminder_create(self, data: dict):
        """Send a reminder_create message to the ESP32 to persist a timer locally."""
        await self._send({"type": "reminder_create", **data})

    async def send_reminder_snooze(self, data: dict):
        """Send a reminder_snooze message so the device can defer a local timer."""
        await self._send({"type": "reminder_snooze", **data})

    async def send_reminder_cancel(self, data: dict):
        """Send a reminder_cancel so the device can drop a local timer (complete/cancel)."""
        await self._send({"type": "reminder_cancel", **data})

    async def send_final(
        self,
        trace_id: str,
        message_id: str,
        ttft_ms: int,
        total_latency_ms: int,
        tools_used: list,
        memory_updated: bool,
    ):
        # tools_used: string[] (legacy) or {tool, status, action?}[] (honest chips)
        await self._send({
            "type": "final",
            "trace_id": trace_id,
            "message_id": message_id,
            "ttft_ms": ttft_ms,
            "total_latency_ms": total_latency_ms,
            "tools_used": tools_used,
            "memory_updated": memory_updated,
        })

    async def send_error(self, code: str, message: str, retry: bool = False):
        await self._send({"type": "error", "code": code, "message": message, "retry": retry})

    async def _send(self, data: dict):
        if self._dead:
            return
        try:
            await self._ws.send_json(data)
        except Exception as e:
            self._dead = True
            logger.error(f"WebSocket send failed, marking connection dead: {e}")
