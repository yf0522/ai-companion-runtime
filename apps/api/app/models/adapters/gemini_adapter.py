from __future__ import annotations

import logging
from typing import AsyncIterator

from google import genai
from google.genai import types

from app.models.adapters.base import ModelAdapter

logger = logging.getLogger(__name__)


def _to_gemini_contents(messages: list[dict]) -> tuple[str | None, list[types.Content]]:
    """Convert OpenAI-style messages to Gemini system instruction + contents."""
    system_parts: list[str] = []
    contents: list[types.Content] = []

    for msg in messages:
        role = msg.get("role", "user")
        text = msg.get("content", "")
        if not text:
            continue
        if role == "system":
            system_parts.append(text)
            continue
        gemini_role = "model" if role == "assistant" else "user"
        contents.append(
            types.Content(role=gemini_role, parts=[types.Part.from_text(text=text)])
        )

    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, contents


class GeminiAdapter(ModelAdapter):
    """Native Gemini adapter using google-genai (supports AQ.* auth keys)."""

    def __init__(
        self,
        provider: str,
        model_name: str,
        api_key: str,
        max_tokens: int = 2048,
        temperature: float = 0.8,
    ):
        self.provider = provider
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = genai.Client(api_key=api_key)

    def _build_config(
        self,
        system_instruction: str | None,
        **kwargs,
    ) -> types.GenerateContentConfig:
        config_kwargs: dict = {
            "max_output_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        return types.GenerateContentConfig(**config_kwargs)

    async def stream_chat(
        self,
        messages: list[dict],
        **kwargs,
    ) -> AsyncIterator[str]:
        system_instruction, contents = _to_gemini_contents(messages)
        config = self._build_config(system_instruction, **kwargs)
        try:
            async for chunk in await self._client.aio.models.generate_content_stream(
                model=self.model_name,
                contents=contents,
                config=config,
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            logger.error(f"[{self.provider}:{self.model_name}] Stream error: {e}")
            raise

    async def chat(
        self,
        messages: list[dict],
        **kwargs,
    ) -> str:
        system_instruction, contents = _to_gemini_contents(messages)
        config = self._build_config(system_instruction, **kwargs)
        try:
            response = await self._client.aio.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )
            return response.text or ""
        except Exception as e:
            logger.error(f"[{self.provider}:{self.model_name}] Chat error: {e}")
            raise

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 2)
