"""ASR endpoint: accepts raw 16kHz mono 16-bit PCM, proxies to DashScope Paraformer.

Uses DashScope SDK's Recognition API which accepts local WAV files
via WebSocket realtime protocol (no file_urls needed).
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import struct
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any

try:
    import dashscope
    from dashscope.audio.asr import Recognition, RecognitionResult
except Exception:  # pragma: no cover - optional dependency in local tests
    dashscope = None  # type: Any

    class RecognitionResult(dict):
        status_code: int = 500
        output: dict[str, list[dict[str, str]]] = {}

    class Recognition:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("dashscope package is not available in this environment")

        def call(self, wav_path: str) -> RecognitionResult:  # noqa: ARG002
            raise RuntimeError("dashscope package is not available in this environment")

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.auth import get_current_user
from app.api.rate_limiter import get_asr_limiter
from app.config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Thread pool for blocking SDK calls (Recognition.call is synchronous)
_executor = ThreadPoolExecutor(max_workers=2)


def _build_wav(pcm_data: bytes, sample_rate: int = 16000, channels: int = 1, bits: int = 16) -> bytes:
    """Wrap raw PCM in a WAV container."""
    byte_rate = sample_rate * channels * (bits // 8)
    block_align = channels * (bits // 8)
    data_size = len(pcm_data)
    riff_size = 36 + data_size

    buf = io.BytesIO()
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", riff_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))
    buf.write(struct.pack("<H", 1))  # PCM
    buf.write(struct.pack("<H", channels))
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", byte_rate))
    buf.write(struct.pack("<H", block_align))
    buf.write(struct.pack("<H", bits))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm_data)
    return buf.getvalue()


def _transcribe_sync(wav_data: bytes, sample_rate: int) -> str:
    """Run DashScope Recognition synchronously (called from thread pool)."""
    if dashscope is None:
        logger.error("ASR: dashscope dependency missing")
        return ""

    # Write WAV data to temp file (Recognition.call() requires a file path)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_data)
        wav_path = f.name

    try:
        dashscope.api_key = settings.qwen_api_key

        recognition = Recognition(
            model="paraformer-realtime-v1",
            format="pcm",
            sample_rate=sample_rate,
            callback=None,
        )

        result: RecognitionResult = recognition.call(wav_path)

        if result.status_code != 200:
            logger.error("ASR: Recognition failed (status=%d)", result.status_code)
            return ""

        output = result.output
        if not output:
            return ""

        # Extract text from sentence list
        sentences = output.get("sentence", [])
        text = "".join(s.get("text", "") for s in sentences)
        return text.strip()

    except Exception as e:
        logger.error("ASR: Recognition error: %s", e)
        return ""
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass


async def _enforce_asr_quota(request: Request, user: dict) -> None:
    user_key = user.get("sub") or (request.client.host if request.client else "unknown")
    allowed = await get_asr_limiter().check(f"asr:{user_key}")
    if not allowed:
        raise HTTPException(status_code=429, detail="ASR rate limit exceeded")


@router.post("/v1/recognize")
async def recognize(
    request: Request,
    user: dict = Depends(get_current_user),
):
    if settings.audio_endpoint_auth_required and not user:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    await _enforce_asr_quota(request, user)

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > settings.max_asr_bytes:
                raise HTTPException(status_code=413, detail="ASR payload too large")
        except ValueError:
            pass

    pcm_data = await request.body()
    if len(pcm_data) > settings.max_asr_bytes:
        raise HTTPException(status_code=413, detail="ASR payload too large")
    if len(pcm_data) < 640:  # minimum ~20ms of audio
        return JSONResponse({"text": ""})

    api_key = settings.qwen_api_key
    if not api_key:
        logger.error("ASR: QWEN_API_KEY not configured")
        return JSONResponse({"text": ""}, status_code=500)

    sample_rate = 16000
    content_type = request.headers.get("content-type", "")
    if "rate=" in content_type:
        try:
            rate_str = content_type.split("rate=")[1].split(";")[0]
            sample_rate = int(rate_str)
        except (ValueError, IndexError):
            pass

    # Build WAV container
    wav_data = _build_wav(pcm_data, sample_rate=sample_rate)

    # Run blocking SDK call in thread pool
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(_executor, _transcribe_sync, wav_data, sample_rate)

    logger.info("ASR: recognized '%s' (%d bytes PCM)", text, len(pcm_data))
    return {"text": text}
