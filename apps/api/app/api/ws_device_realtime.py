from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

try:
    import dashscope
    from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
except Exception:  # pragma: no cover - optional runtime dependency in local/dev tests
    dashscope = None  # type: Any

    class RecognitionCallback:
        def on_event(self, result: object) -> None:
            return None

        def on_complete(self) -> None:
            return None

        def on_error(self, result: object) -> None:
            return None

    class RecognitionResult(dict):
        def get_sentence(self) -> list[dict[str, Any]]:
            return []

    class Recognition:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("dashscope package is not available in this environment")

        def start(self) -> None:
            raise RuntimeError("dashscope package is not available in this environment")

        def send_audio_frame(self, frame: bytes) -> None:
            return None

        def stop(self) -> None:
            raise RuntimeError("dashscope package is not available in this environment")
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.api.asr import _build_wav, _executor, _transcribe_sync
from app.config.settings import settings
from app.runtime.device_identity import (
    MAX_AUDIO_FRAME_BYTES,
    MAX_AUDIO_TURN_BYTES,
    MAX_DEVICE_MESSAGE_BYTES,
    SUPPORTED_SAMPLE_RATES,
    DevicePrincipal,
    advance_device_sequence,
    authenticate_device_from_message,
    require_next_sequence,
)
from app.db.session import async_session
from app.runtime import session_service
from app.runtime.agent_runtime import DEFAULT_RUNTIME, get_agent_runtime, normalize_runtime_name
from app.runtime.device_stream_manager import DeviceStreamManager

logger = logging.getLogger(__name__)
router = APIRouter()

_AUTH_TIMEOUT_S = 10


class DeviceProtocolState:
    def __init__(self, principal: DevicePrincipal) -> None:
        self.principal = principal
        self.high_watermark = principal.sequence_high_watermark
        self.audio_active = False
        self.audio_bytes = 0

    def accept_sequence(self, data: dict[str, Any]) -> int:
        sequence = require_next_sequence(data.get("seq"), self.high_watermark)
        return sequence

    def mark_sequence_accepted(self, sequence: int) -> None:
        self.high_watermark = sequence

    def reset_audio_turn(self) -> None:
        self.audio_active = True
        self.audio_bytes = 0

    def accept_audio_frame(self, size: int) -> None:
        if not self.audio_active:
            raise ValueError("audio_not_started")
        if size > MAX_AUDIO_FRAME_BYTES:
            raise ValueError("audio_frame_too_large")
        self.audio_bytes += size
        if self.audio_bytes > MAX_AUDIO_TURN_BYTES:
            raise ValueError("audio_turn_too_large")

    def end_audio_turn(self) -> None:
        self.audio_active = False


async def transcribe_pcm(pcm_data: bytes, sample_rate: int = 16000) -> str:
    if len(pcm_data) < 640:
        return ""
    wav_data = _build_wav(pcm_data, sample_rate=sample_rate)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _transcribe_sync, wav_data, sample_rate)


class _RealtimeAsrCallback(RecognitionCallback):
    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[dict[str, object] | None]) -> None:
        self._loop = loop
        self._queue = queue

    def on_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        items = sentence if isinstance(sentence, list) else [sentence]
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            event = {
                "type": "asr_partial",
                "text": text,
                "is_final": item.get("end_time") is not None,
                "begin_time": item.get("begin_time"),
                "end_time": item.get("end_time"),
            }
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    def on_complete(self) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, None)

    def on_error(self, result: RecognitionResult) -> None:
        logger.error("Realtime ASR error: %r", result)
        self._loop.call_soon_threadsafe(self._queue.put_nowait, None)


class RealtimeAsrSession:
    def __init__(self, sample_rate: int) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()
        self._final_by_begin: dict[int, str] = {}
        self._latest_text = ""
        self._recognition = Recognition(
            model="paraformer-realtime-v1",
            callback=_RealtimeAsrCallback(self._loop, self._queue),
            format="pcm",
            sample_rate=sample_rate,
        )

    async def start(self) -> None:
        dashscope.api_key = settings.qwen_api_key
        await asyncio.to_thread(self._recognition.start)

    def send_audio(self, data: bytes) -> None:
        if data:
            self._recognition.send_audio_frame(data)

    async def stop(self) -> str:
        await asyncio.to_thread(self._recognition.stop)
        await self._drain_events()
        if self._final_by_begin:
            return "".join(text for _, text in sorted(self._final_by_begin.items())).strip()
        return self._latest_text.strip()

    async def next_event(self, timeout: float = 0.0) -> dict[str, object] | None:
        try:
            if timeout > 0:
                event = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            else:
                event = self._queue.get_nowait()
        except (asyncio.QueueEmpty, TimeoutError):
            return None
        if event is None:
            return None
        self._remember_event(event)
        return event

    async def _drain_events(self) -> None:
        while True:
            event = await self.next_event()
            if event is None:
                break

    def _remember_event(self, event: dict[str, object]) -> None:
        text = str(event.get("text") or "").strip()
        if not text:
            return
        self._latest_text = text
        if event.get("is_final"):
            begin = event.get("begin_time")
            key = int(begin) if isinstance(begin, (int, float)) else len(self._final_by_begin)
            self._final_by_begin[key] = text


async def _run_device_harness(
    websocket: WebSocket,
    *,
    user_id: str,
    session_id: str,
    transcript: str,
    agent_runtime: str = DEFAULT_RUNTIME,
) -> dict:
    stream_mgr = DeviceStreamManager(websocket)
    cancel_event = asyncio.Event()
    runtime = get_agent_runtime(agent_runtime)
    return await runtime.run(
        user_id=user_id,
        session_id=session_id,
        message=transcript,
        stream_mgr=stream_mgr,
        cancel_event=cancel_event,
    )


async def _persist_device_sequence(
    websocket: WebSocket,
    protocol: DeviceProtocolState,
    *,
    sequence: int,
    device_id: str,
    **kwargs: Any,
) -> bool:
    try:
        async with async_session() as db:
            await advance_device_sequence(
                db,
                device_id=uuid.UUID(device_id),
                sequence=sequence,
                **kwargs,
            )
    except ValueError as exc:
        await websocket.send_json({"type": "error", "code": str(exc), "retry": False})
        await websocket.close(code=4003, reason="Protocol violation")
        return False
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "code": str(exc.detail), "retry": False})
        await websocket.close(code=4003, reason="Protocol violation")
        return False
    protocol.mark_sequence_accepted(sequence)
    return True


@router.websocket("/ws/device/realtime")
async def ws_device_realtime(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=_AUTH_TIMEOUT_S)
        if len(raw.encode("utf-8")) > MAX_DEVICE_MESSAGE_BYTES:
            raise ValueError("auth_message_too_large")
        data = json.loads(raw)
    except Exception:
        await websocket.send_json({"type": "error", "code": "auth_required", "retry": False})
        await websocket.close(code=4001, reason="Auth required")
        return

    if data.get("type") != "auth" or data.get("auth_type") != "device":
        await websocket.send_json({"type": "error", "code": "auth_required", "retry": False})
        await websocket.close(code=4001, reason="Auth required")
        return

    principal = await authenticate_device_from_message(data)
    if principal is None:
        await websocket.send_json({"type": "error", "code": "auth_failed", "retry": False})
        await websocket.close(code=4001, reason="Unauthorized")
        return

    try:
        agent_runtime = normalize_runtime_name(
            data.get("agent_runtime") or data.get("runtime")
        )
    except ValueError as exc:
        await websocket.send_json({
            "type": "error",
            "code": "invalid_runtime",
            "message": str(exc),
            "retry": False,
        })
        await websocket.close(code=4002, reason="Invalid agent runtime")
        return

    protocol = DeviceProtocolState(principal)
    session_id = await session_service.ensure_session(principal.user_id, data.get("session_id"))
    await websocket.send_json({
        "type": "connected",
        "mode": "realtime",
        "session_id": session_id,
        "agent_runtime": agent_runtime,
        "device_id": principal.device_id,
        "protocol": {
            "max_message_bytes": MAX_DEVICE_MESSAGE_BYTES,
            "max_audio_frame_bytes": MAX_AUDIO_FRAME_BYTES,
            "max_audio_turn_bytes": MAX_AUDIO_TURN_BYTES,
            "sequence": "strictly_increasing_by_one",
        },
    })
    logger.info(
        "Realtime device connected: device=%s user=%s session=%s",
        principal.device_id,
        principal.user_id,
        session_id,
    )

    pcm = bytearray()
    sample_rate = 16000
    asr_session: RealtimeAsrSession | None = None
    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                try:
                    protocol.accept_audio_frame(len(msg["bytes"]))
                except ValueError as exc:
                    await websocket.send_json(
                        {"type": "error", "code": str(exc), "retry": False}
                    )
                    await websocket.close(code=4003, reason="Protocol violation")
                    return
                pcm.extend(msg["bytes"])
                if asr_session is not None:
                    asr_session.send_audio(msg["bytes"])
                    while (event := await asr_session.next_event()) is not None:
                        await websocket.send_json(event)
                continue

            text = msg.get("text")
            if text is None:
                continue
            if len(text.encode("utf-8")) > MAX_DEVICE_MESSAGE_BYTES:
                await websocket.send_json(
                    {"type": "error", "code": "message_too_large", "retry": False}
                )
                await websocket.close(code=4003, reason="Protocol violation")
                return

            data = json.loads(text)
            msg_type = data.get("type")
            try:
                seq = protocol.accept_sequence(data)
            except ValueError as exc:
                await websocket.send_json(
                    {"type": "error", "code": str(exc), "retry": False}
                )
                await websocket.close(code=4003, reason="Protocol violation")
                return

            if msg_type == "ping":
                if not await _persist_device_sequence(
                    websocket,
                    protocol,
                    sequence=seq,
                    device_id=principal.device_id,
                ):
                    return
                await websocket.send_json({"type": "pong", "seq": seq})
            elif msg_type == "heartbeat":
                if not await _persist_device_sequence(
                    websocket,
                    protocol,
                    sequence=seq,
                    device_id=principal.device_id,
                    health=data.get("health") if isinstance(data.get("health"), dict) else {},
                    firmware_version=data.get("firmware_version")
                    if isinstance(data.get("firmware_version"), str)
                    else None,
                ):
                    return
                await websocket.send_json(
                    {
                        "type": "heartbeat_ack",
                        "seq": seq,
                        "device_id": principal.device_id,
                    }
                )
            elif msg_type in {"receipt", "command_receipt"}:
                command_id = data.get("command_id")
                receipt_type = data.get("receipt_type")
                if not isinstance(command_id, str) or not isinstance(receipt_type, str):
                    await websocket.send_json(
                        {"type": "error", "code": "receipt_correlation_required", "retry": False}
                    )
                    await websocket.close(code=4003, reason="Protocol violation")
                    return
                if not await _persist_device_sequence(
                    websocket,
                    protocol,
                    sequence=seq,
                    device_id=principal.device_id,
                    command_id=command_id,
                    receipt_type=receipt_type,
                    receipt_metadata=data.get("metadata")
                    if isinstance(data.get("metadata"), dict)
                    else {},
                ):
                    return
                await websocket.send_json(
                    {
                        "type": "receipt_ack",
                        "seq": seq,
                        "command_id": command_id,
                        "receipt_type": receipt_type,
                    }
                )
            elif msg_type == "audio_start":
                pcm.clear()
                sample_rate = int(data.get("sample_rate") or 16000)
                if sample_rate not in SUPPORTED_SAMPLE_RATES:
                    await websocket.send_json(
                        {"type": "error", "code": "unsupported_sample_rate", "retry": False}
                    )
                    await websocket.close(code=4003, reason="Protocol violation")
                    return
                if not await _persist_device_sequence(
                    websocket,
                    protocol,
                    sequence=seq,
                    device_id=principal.device_id,
                ):
                    return
                if asr_session is not None:
                    await asr_session.stop()
                asr_session = None
                protocol.reset_audio_turn()
                await websocket.send_json({"type": "listening"})
            elif msg_type == "audio_end":
                if not await _persist_device_sequence(
                    websocket,
                    protocol,
                    sequence=seq,
                    device_id=principal.device_id,
                ):
                    return
                protocol.end_audio_turn()
                start = time.monotonic()
                if asr_session is not None:
                    transcript = await asr_session.stop()
                    asr_session = None
                    if not transcript and len(pcm) >= 640:
                        logger.info(
                            "Realtime ASR returned empty, falling back to batch ASR: pcm=%d",
                            len(pcm),
                        )
                        transcript = await transcribe_pcm(
                            bytes(pcm), sample_rate=sample_rate
                        )
                else:
                    transcript = await transcribe_pcm(
                        bytes(pcm), sample_rate=sample_rate
                    )
                await websocket.send_json({"type": "asr_final", "text": transcript})
                if transcript:
                    await _run_device_harness(
                        websocket,
                        user_id=principal.user_id,
                        session_id=session_id,
                        transcript=transcript,
                        agent_runtime=agent_runtime,
                    )
                    asyncio.create_task(
                        session_service.increment_message_count(session_id)
                    )
                else:
                    await websocket.send_json(
                        {"type": "no_speech", "reason": "empty_transcript"}
                    )
                logger.info(
                    "Realtime turn done: pcm=%d transcript=%r latency_ms=%d",
                    len(pcm),
                    transcript,
                    int((time.monotonic() - start) * 1000),
                )
                pcm.clear()
            else:
                if not await _persist_device_sequence(
                    websocket,
                    protocol,
                    sequence=seq,
                    device_id=principal.device_id,
                ):
                    return
                await websocket.send_json(
                    {"type": "error", "code": "unknown_type", "retry": False}
                )
    except WebSocketDisconnect:
        logger.info("Realtime device disconnected: device=%s user=%s", principal.device_id, principal.user_id)
