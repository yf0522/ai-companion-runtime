from __future__ import annotations

import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from app.models.adapters.base import ModelAdapter

logger = logging.getLogger(__name__)


class OpenAICompatibleAdapter(ModelAdapter):
    """Adapter for any OpenAI-compatible API (OpenAI, Qwen, DeepSeek, etc.)."""

    def __init__(
        self,
        provider: str,
        model_name: str,
        api_key: str,
        base_url: str,
        max_tokens: int = 2048,
        temperature: float = 0.8,
    ):
        self.provider = provider
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def stream_chat(
        self,
        messages: list[dict],
        **kwargs,
    ) -> AsyncIterator[str]:
        try:
            response = await self._client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                temperature=kwargs.get("temperature", self.temperature),
                stream=True,
            )
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"[{self.provider}:{self.model_name}] Stream error: {e}")
            raise

    async def chat(
        self,
        messages: list[dict],
        **kwargs,
    ) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                temperature=kwargs.get("temperature", self.temperature),
                stream=False,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"[{self.provider}:{self.model_name}] Chat error: {e}")
            raise

    def count_tokens(self, text: str) -> int:
        # Rough estimate: ~1.5 chars per token for Chinese, ~4 chars for English
        return max(1, len(text) // 2)
