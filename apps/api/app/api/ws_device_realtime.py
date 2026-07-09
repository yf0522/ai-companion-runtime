from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
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
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.auth import decode_token
from app.api.asr import _build_wav, _executor, _transcribe_sync
from app.api.tts import stream_synthesize_pcm
from app.config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()

_AUTH_TIMEOUT_S = 10


async def transcribe_pcm(pcm_data: bytes, sample_rate: int = 16000) -> str:
    if len(pcm_data) < 640:
        return ""
    wav_data = _build_wav(pcm_data, sample_rate=sample_rate)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _transcribe_sync, wav_data, sample_rate)


async def stream_reply_text(text: str) -> AsyncIterator[str]:
    from app.models.router import model_router

    try:
        model = await model_router.get_model("fast")
        messages = [
            {"role": "system", "content": "你是一个简短、温暖的中文语音陪伴助手。回复必须适合朗读，控制在40字内。"},
            {"role": "user", "content": text},
        ]
        provider = getattr(model, "provider", "unknown")
        model_name = getattr(model, "model_name", "unknown")
        logger.info("Realtime model stream started: provider=%s model=%s", provider, model_name)
        async for token in model.stream_chat(messages):
            yield token
        logger.info("Realtime model stream done: provider=%s model=%s", provider, model_name)
    except Exception as e:
        logger.warning("Realtime model failed, using template reply: %s", e)
        yield "模型有点慢，我先陪你一下。"


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


async def _send_tts_segments(
    websocket: WebSocket,
    text_stream: AsyncIterator[str],
    *,
    first_sent: bool = False,
) -> str:
    full_text = ""
    first = not first_sent

    async for token in text_stream:
        if not token:
            continue
        full_text += token
        if first:
            await websocket.send_json({"type": "first_reply", "text": token})
            first = False
        else:
            await websocket.send_json({"type": "delta", "text": token})

    if first:
        fallback = "模型暂时没有回复。"
        full_text = fallback
        await websocket.send_json({"type": "first_reply", "text": fallback})
        async for chunk in stream_synthesize_pcm(fallback):
            await websocket.send_bytes(chunk)
    elif full_text.strip():
        async for chunk in stream_synthesize_pcm(full_text):
            await websocket.send_bytes(chunk)

    await websocket.send_json({"type": "tts_done"})
    return full_text


@router.websocket("/ws/device/realtime")
async def ws_device_realtime(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=_AUTH_TIMEOUT_S)
        data = json.loads(raw)
    except Exception:
        await websocket.send_json({"type": "error", "code": "auth_required", "retry": False})
        await websocket.close(code=4001, reason="Auth required")
        return

    if data.get("type") != "auth" or not data.get("token"):
        await websocket.send_json({"type": "error", "code": "auth_required", "retry": False})
        await websocket.close(code=4001, reason="Auth required")
        return

    payload = decode_token(data["token"])
    if not payload or "sub" not in payload:
        await websocket.send_json({"type": "error", "code": "auth_failed", "retry": False})
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.send_json({"type": "connected", "mode": "realtime"})
    logger.info("Realtime device connected: user=%s", payload["sub"])

    pcm = bytearray()
    sample_rate = 16000
    asr_session: RealtimeAsrSession | None = None
    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                pcm.extend(msg["bytes"])
                if asr_session is not None:
                    asr_session.send_audio(msg["bytes"])
                    while (event := await asr_session.next_event()) is not None:
                        await websocket.send_json(event)
                continue

            text = msg.get("text")
            if text is None:
                continue

            data = json.loads(text)
            msg_type = data.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "audio_start":
                pcm.clear()
                sample_rate = int(data.get("sample_rate") or 16000)
                if asr_session is not None:
                    await asr_session.stop()
                asr_session = None
                await websocket.send_json({"type": "listening"})
            elif msg_type == "audio_end":
                start = time.monotonic()
                if asr_session is not None:
                    transcript = await asr_session.stop()
                    asr_session = None
                    if not transcript and len(pcm) >= 640:
                        logger.info("Realtime ASR returned empty, falling back to batch ASR: pcm=%d", len(pcm))
                        transcript = await transcribe_pcm(bytes(pcm), sample_rate=sample_rate)
                else:
                    transcript = await transcribe_pcm(bytes(pcm), sample_rate=sample_rate)
                await websocket.send_json({"type": "asr_final", "text": transcript})
                if transcript:
                    await _send_tts_segments(websocket, stream_reply_text(transcript))
                else:
                    await websocket.send_json({"type": "no_speech", "reason": "empty_transcript"})
                logger.info(
                    "Realtime turn done: pcm=%d transcript=%r latency_ms=%d",
                    len(pcm),
                    transcript,
                    int((time.monotonic() - start) * 1000),
                )
                pcm.clear()
            else:
                await websocket.send_json({"type": "error", "code": "unknown_type", "retry": False})
    except WebSocketDisconnect:
        logger.info("Realtime device disconnected: user=%s", payload["sub"])


async def _single_text(text: str) -> AsyncIterator[str]:
    yield text
