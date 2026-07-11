"""Optional mem0 OSS engine backend (AsyncMemory).

Enable with ``MEM0_ENABLED=1`` (or Settings.mem0_enabled) and optional
``MEM0_CONFIG_JSON`` (mem0 ``from_config`` dict). Without a usable config /
LLM+embedder, ``try_build_mem0_backend`` returns None and ``get_memory_backend``
installs a degraded mem0 stub (empty search, **no** lifecycle dump).

Consent, CareTask boundary, and refuse rules stay outside this module.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class Mem0MemoryBackend:
    """Real mem0 ``AsyncMemory`` integration behind MemoryEngineBackend."""

    name = "mem0"

    def __init__(self, memory: Any) -> None:
        self._memory = memory

    async def add(
        self,
        *,
        user_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        infer: bool = False,
    ) -> str | None:
        meta = dict(metadata or {})
        # Prefer infer=False for explicit tool notes — we already classified/refused.
        result = await self._memory.add(
            content,
            user_id=str(user_id),
            metadata=meta,
            infer=infer,
        )
        return _extract_mem0_id(result)

    async def search(
        self,
        *,
        user_id: str,
        query: str,
        limit: int = 5,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"user_id": str(user_id)}
        if metadata_filters:
            # mem0 metadata operators — pass through non-time keys lightly.
            for key, value in metadata_filters.items():
                if key in {"time_from", "time_to", "purpose"}:
                    continue
                filters[key] = value
        result = await self._memory.search(
            query or "preferences and household facts",
            top_k=max(1, min(limit, 20)),
            filters=filters,
        )
        rows = result.get("results") if isinstance(result, dict) else result
        if not isinstance(rows, list):
            return []
        out: list[dict[str, Any]] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            content = row.get("memory") or row.get("content") or ""
            out.append(
                {
                    "id": str(row.get("id") or ""),
                    "content": content,
                    "score": float(row.get("score") or 0.0),
                    "category": (row.get("metadata") or {}).get("category"),
                    "sensitivity": (row.get("metadata") or {}).get("sensitivity"),
                    "created_at": row.get("created_at"),
                    "metadata": row.get("metadata") or {},
                }
            )
        return out


def try_build_mem0_backend() -> Mem0MemoryBackend | None:
    """Build AsyncMemory from env; return None if unavailable."""
    try:
        from mem0 import AsyncMemory
    except ImportError:
        logger.warning("mem0ai not installed; skip mem0 backend")
        return None

    config = _load_mem0_config()
    try:
        if config:
            memory = AsyncMemory.from_config(config)
        else:
            # Default OSS config requires provider keys; may still construct for tests
            # that inject a fake. Prefer explicit MEM0_CONFIG_JSON in real deploys.
            memory = AsyncMemory()
        return Mem0MemoryBackend(memory)
    except Exception as e:
        logger.warning("AsyncMemory init failed: %s", e)
        return None


def _load_mem0_config() -> dict[str, Any] | None:
    raw = os.environ.get("MEM0_CONFIG_JSON", "").strip()
    if not raw:
        try:
            from app.config.settings import settings

            raw = (settings.mem0_config_json or "").strip()
        except Exception:
            raw = ""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        logger.error("MEM0_CONFIG_JSON is not valid JSON")
        return None


def _extract_mem0_id(result: Any) -> str | None:
    if result is None:
        return None
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        results = result.get("results")
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict) and first.get("id"):
                return str(first["id"])
        if result.get("id"):
            return str(result["id"])
    return None
