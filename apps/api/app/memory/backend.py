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


class DegradedMem0Backend:
    """Honest empty engine when MEM0_ENABLED but AsyncMemory is unavailable.

    Keeps ``name == \"mem0\"`` so the adapter never falls through to lifecycle dump
    (ADR-003 / A3). Consent SoT remains Postgres lifecycle writes in the adapter.
    """

    name = "mem0"
    degraded = True

    async def add(
        self,
        *,
        user_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        infer: bool = False,
    ) -> str | None:
        logger.info("mem0 degraded: skip add (user_id=%s)", user_id)
        return None

    async def search(
        self,
        *,
        user_id: str,
        query: str,
        limit: int = 5,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        logger.info("mem0 degraded: empty search (user_id=%s)", user_id)
        return []


def mem0_enabled() -> bool:
    """True when MEM0_ENABLED env/settings requests the mem0 engine path."""
    env = os.environ.get("MEM0_ENABLED", "").strip().lower()
    if env in {"1", "true", "yes"}:
        return True
    if env in {"0", "false", "no"}:
        return False
    try:
        from app.config.settings import settings

        return bool(settings.mem0_enabled)
    except Exception:
        return False


def get_memory_backend() -> MemoryEngineBackend:
    """Prefer mem0 when enabled; on init failure use degraded mem0 (no lifecycle dump).

    Lifecycle dump / importance top-N is only used when ``backend.name == \"lifecycle\"``
    (MEM0_ENABLED off).
    """
    if mem0_enabled():
        try:
            from app.memory.mem0_backend import try_build_mem0_backend
            from app.observability.metrics import MEMORY_ENGINE_TOTAL

            backend = try_build_mem0_backend()
            if backend is not None:
                logger.info("memory backend: mem0 (%s)", backend.name)
                MEMORY_ENGINE_TOTAL.labels(engine="mem0", event="backend_ready").inc()
                return backend
            logger.warning(
                "MEM0_ENABLED but AsyncMemory init failed; using degraded mem0 "
                "(empty/no-dump — not lifecycle)"
            )
            MEMORY_ENGINE_TOTAL.labels(engine="mem0", event="unavailable").inc()
            return DegradedMem0Backend()
        except Exception as e:
            logger.warning(
                "mem0 backend unavailable (%s); using degraded mem0 (no lifecycle dump)",
                e,
            )
            try:
                from app.observability.metrics import MEMORY_ENGINE_TOTAL

                MEMORY_ENGINE_TOTAL.labels(engine="mem0", event="unavailable").inc()
            except Exception:
                pass
            return DegradedMem0Backend()

    from app.memory.lifecycle_backend import LifecycleMemoryBackend

    return LifecycleMemoryBackend()
