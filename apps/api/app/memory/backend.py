"""Memory engine backend protocol — OSS mem0 or lifecycle store."""
from __future__ import annotations

import logging
import os
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class MemoryEngineBackend(Protocol):
    """Thin engine interface: extract/store/rank. Consent stays in the adapter."""

    name: str

    async def add(
        self,
        *,
        user_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        infer: bool = False,
    ) -> str | None:
        """Store content; return engine-side id if available."""
        ...

    async def search(
        self,
        *,
        user_id: str,
        query: str,
        limit: int = 5,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Ranked fragments: id?, content, score?, metadata?."""
        ...


def mem0_enabled() -> bool:
    return os.environ.get("MEM0_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def get_memory_backend() -> MemoryEngineBackend:
    """Prefer mem0 when enabled and importable; otherwise lifecycle store."""
    if mem0_enabled():
        try:
            from app.memory.mem0_backend import try_build_mem0_backend

            backend = try_build_mem0_backend()
            if backend is not None:
                logger.info("memory backend: mem0 (%s)", backend.name)
                return backend
            logger.warning("MEM0_ENABLED but AsyncMemory init failed; using lifecycle backend")
        except Exception as e:
            logger.warning("mem0 backend unavailable (%s); using lifecycle backend", e)
    from app.memory.lifecycle_backend import LifecycleMemoryBackend

    return LifecycleMemoryBackend()
