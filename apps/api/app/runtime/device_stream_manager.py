"""Device-facing stream manager: JSON events + spoken TTS after final."""
from __future__ import annotations

import logging

from fastapi import WebSocket

from app.api.tts import stream_synthesize_pcm
from app.runtime.stream_manager import StreamManager

logger = logging.getLogger(__name__)


class DeviceStreamManager(StreamManager):
    """Same JSON protocol as chat, plus PCM TTS after the final event."""

    def __init__(self, websocket: WebSocket):
        super().__init__(websocket)
        self._spoken_parts: list[str] = []
        self._tts_done = False

    async def send_first_reply(self, text: str, ttft_ms: int):
        if text:
            self._spoken_parts.append(text)
        await super().send_first_reply(text, ttft_ms)

    async def send_delta(self, text: str):
        if text:
            self._spoken_parts.append(text)
        await super().send_delta(text)

    async def send_risk_alert(self, level: str, message: str):
        # Risk safety text is also spoken to the elder device.
        if message:
            self._spoken_parts.append(message)
        await super().send_risk_alert(level, message)

    async def send_final(
        self,
        trace_id: str,
        message_id: str,
        ttft_ms: int,
        total_latency_ms: int,
        tools_used: list[str],
        memory_updated: bool,
    ):
        await super().send_final(
            trace_id=trace_id,
            message_id=message_id,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tools_used=tools_used,
            memory_updated=memory_updated,
        )
        await self._flush_tts()

    async def _flush_tts(self) -> None:
        if self._tts_done:
            return
        self._tts_done = True
        spoken = "".join(self._spoken_parts).strip()
        if spoken:
            try:
                async for chunk in stream_synthesize_pcm(spoken):
                    if chunk and not self.dead:
                        try:
                            await self._ws.send_bytes(chunk)
                        except Exception as e:
                            self._dead = True
                            logger.error(f"Device TTS bytes send failed: {e}")
                            break
            except Exception as e:
                logger.error(f"Device TTS synthesis failed: {e}")
        await self._send({"type": "tts_done"})
