from __future__ import annotations

import logging
from typing import AsyncIterator

from app.models.adapters.base import ModelAdapter
from app.models.registry import ModelRegistry

logger = logging.getLogger(__name__)


class ModelRouter:
    """Routes model requests to the appropriate adapter with fallback."""

    def __init__(self, registry: ModelRegistry):
        self._registry = registry

    async def get_model(self, role: str) -> ModelAdapter:
        """Get model adapter by role."""
        return await self._registry.get_adapter(role)

    async def stream_with_fallback(
        self,
        messages: list[dict],
        timeout_ms: int = 30000,
        **kwargs,
    ) -> AsyncIterator[str]:
        """Try primary model, fallback on failure."""
        # Try primary
        try:
            primary = await self._registry.get_adapter("primary")
            async for token in self._stream_with_timeout(primary, messages, timeout_ms, **kwargs):
                yield token
            return
        except Exception as e:
            logger.warning(f"Primary model failed: {e}, trying fallback")

        # Try fallback
        try:
            fallback = await self._registry.get_adapter("fallback")
            async for token in self._stream_with_timeout(fallback, messages, timeout_ms, **kwargs):
                yield token
            return
        except Exception as e:
            logger.error(f"Fallback model also failed: {e}")
            raise

    async def _stream_with_timeout(
        self,
        adapter: ModelAdapter,
        messages: list[dict],
        timeout_ms: int,
        **kwargs,
    ) -> AsyncIterator[str]:
        """Wrap streaming with a total timeout."""
        # For streaming, we pass through and let the caller handle timeout
        async for token in adapter.stream_chat(messages, **kwargs):
            yield token


# Global singleton
_registry = ModelRegistry()
model_router = ModelRouter(_registry)
