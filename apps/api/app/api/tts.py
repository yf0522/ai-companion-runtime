"""TTS endpoint: synthesizes text to 24kHz mono PCM for the ESP32 client."""

from __future__ import annotations

import logging
import unicodedata
import asyncio
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter()

_DASHSCOPE_BASE = "https://dashscope.aliyuncs.com"
_TTS_MODEL = "cosyvoice-v3-flash"
_TTS_VOICE = "longanyang"
_TTS_SAMPLE_RATE = 24000


def _has_pronounceable_text(text: str) -> bool:
    return any(unicodedata.category(ch)[0] in {"L", "N", "P", "Z"} for ch in text)


@router.post("/v1/synthesize")
async def synthesize(request: Request):
    api_key = settings.qwen_api_key
    if not api_key:
        logger.error("TTS: QWEN_API_KEY not configured")
        return Response(status_code=500)

    try:
        body = await request.json()
    except Exception:
        return Response(content=b"", status_code=400)

    text = body.get("text", "").strip()
    if not text:
        return Response(content=b"", media_type="audio/pcm")
    if not _has_pronounceable_text(text):
        return Response(content=b"", media_type="audio/pcm")

    try:
        audio_data = await synthesize_pcm(text)
        if not audio_data:
            logger.error("TTS: empty audio for text=%r", text[:50])
            return Response(content=b"", status_code=500)

        logger.info(
            "TTS: synthesized %d chars -> %d bytes PCM (model=%s, voice=%s)",
            len(text),
            len(audio_data),
            _TTS_MODEL,
            _TTS_VOICE,
        )
        return Response(content=audio_data, media_type="audio/pcm")

    except Exception as e:
        logger.error("TTS: synthesis error: %s", e)
        return Response(content=b"", status_code=500)


async def synthesize_pcm(text: str) -> bytes:
    api_key = settings.qwen_api_key
    if not api_key or not text.strip() or not _has_pronounceable_text(text):
        return b""

    payload = {
        "model": _TTS_MODEL,
        "input": {
            "text": text.strip(),
            "voice": _TTS_VOICE,
            "format": "pcm",
            "sample_rate": _TTS_SAMPLE_RATE,
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{_DASHSCOPE_BASE}/api/v1/services/audio/tts/SpeechSynthesizer",
            headers=headers,
            json=payload,
        )
        if resp.status_code != 200:
            logger.error("TTS: DashScope failed (status=%d, body=%s)", resp.status_code, resp.text[:200])
            return b""

        audio_url = resp.json().get("output", {}).get("audio", {}).get("url", "")
        if not audio_url:
            logger.error("TTS: DashScope response missing audio URL: %s", resp.text[:200])
            return b""

        audio_resp = await client.get(audio_url)
        if audio_resp.status_code != 200:
            logger.error("TTS: audio download failed (status=%d)", audio_resp.status_code)
            return b""
        return audio_resp.content


async def stream_synthesize_pcm(text: str) -> AsyncIterator[bytes]:
    if not settings.qwen_api_key or not text.strip() or not _has_pronounceable_text(text):
        return

    try:
        audio = await asyncio.wait_for(synthesize_pcm(text), timeout=4.0)
    except TimeoutError:
        logger.error("TTS: timed out for text=%r", text[:50])
        return
    if audio:
        yield audio
