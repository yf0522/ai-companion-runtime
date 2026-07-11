from __future__ import annotations

import asyncio
import logging
from typing import Protocol, runtime_checkable

from app.runtime.stream_manager import StreamManager

logger = logging.getLogger(__name__)

# Canonical production runtime is Pi. Harness remains importable until Phase 5 soak+delete
# but is NOT the default and must not be used as a silent fallback.
RUNTIME_PI = "pi"
RUNTIME_PI_EXPERIMENTAL = "pi_experimental"  # legacy alias → pi
RUNTIME_HARNESS = "harness"

SUPPORTED_RUNTIMES: frozenset[str] = frozenset({RUNTIME_PI, RUNTIME_HARNESS})
DEFAULT_RUNTIME = RUNTIME_PI

_ALIASES: dict[str, str] = {
    "pi": RUNTIME_PI,
    "pi_experimental": RUNTIME_PI,
    "experimental": RUNTIME_PI,
    "default": RUNTIME_PI,
    "harness": RUNTIME_HARNESS,
    "standard": RUNTIME_HARNESS,
}


@runtime_checkable
class AgentRuntime(Protocol):
    """Pluggable agent execution path (production Pi; harness retained until Phase 5)."""

    name: str

    async def run(
        self,
        user_id: str,
        session_id: str,
        message: str,
        stream_mgr: StreamManager,
        cancel_event: asyncio.Event,
    ) -> dict:
        ...


def normalize_runtime_name(name: str | None) -> str:
    """Map client/runtime aliases to canonical runtime ids."""
    if not name:
        return DEFAULT_RUNTIME
    key = str(name).strip().lower()
    if key not in _ALIASES:
        supported = ", ".join(sorted(SUPPORTED_RUNTIMES))
        raise ValueError(f"Unknown agent runtime '{name}'. Supported: {supported}")
    return _ALIASES[key]


def get_agent_runtime(name: str | None) -> AgentRuntime:
    """Factory for agent runtimes. Default is Pi (no harness silent fallback)."""
    runtime_id = normalize_runtime_name(name)
    if runtime_id == RUNTIME_PI:
        from app.runtime.pi_runtime import PiExperimentalRuntime

        return PiExperimentalRuntime()
    if runtime_id == RUNTIME_HARNESS:
        # Temporary until Phase 5 physical delete — explicit request only, never default.
        from app.runtime.harness_runtime import HarnessRuntime

        logger.warning(
            "Harness runtime requested explicitly; production default is Pi. "
            "Harness will be removed after gate C + soak."
        )
        return HarnessRuntime()
    raise ValueError(f"Unsupported runtime: {runtime_id}")
