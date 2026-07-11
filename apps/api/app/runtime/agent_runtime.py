from __future__ import annotations

import asyncio
import logging
from typing import Protocol, runtime_checkable

from app.runtime.stream_manager import StreamManager

logger = logging.getLogger(__name__)

# Canonical (and sole) production runtime is Pi. Harness was physically deleted in Phase 5.
RUNTIME_PI = "pi"
RUNTIME_PI_EXPERIMENTAL = "pi_experimental"  # legacy alias → pi

SUPPORTED_RUNTIMES: frozenset[str] = frozenset({RUNTIME_PI})
DEFAULT_RUNTIME = RUNTIME_PI

_ALIASES: dict[str, str] = {
    "pi": RUNTIME_PI,
    "pi_experimental": RUNTIME_PI,
    "experimental": RUNTIME_PI,
    "default": RUNTIME_PI,
}

# Explicitly rejected names (no FF escape).
_REJECTED_RUNTIMES: frozenset[str] = frozenset({"harness", "standard", "agent_harness"})


@runtime_checkable
class AgentRuntime(Protocol):
    """Pluggable agent execution path — production Pi only."""

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
    """Map client/runtime aliases to the sole Pi runtime id."""
    if not name:
        return DEFAULT_RUNTIME
    key = str(name).strip().lower()
    if key in _REJECTED_RUNTIMES:
        raise ValueError(
            f"Agent runtime '{name}' is unsupported. Production is Pi-only "
            f"(supported: {', '.join(sorted(SUPPORTED_RUNTIMES))})."
        )
    if key not in _ALIASES:
        supported = ", ".join(sorted(SUPPORTED_RUNTIMES))
        raise ValueError(f"Unknown agent runtime '{name}'. Supported: {supported}")
    return _ALIASES[key]


def get_agent_runtime(name: str | None) -> AgentRuntime:
    """Factory for agent runtimes. Pi only — harness requests raise."""
    runtime_id = normalize_runtime_name(name)
    if runtime_id == RUNTIME_PI:
        from app.runtime.pi_runtime import PiExperimentalRuntime

        return PiExperimentalRuntime()
    raise ValueError(f"Unsupported runtime: {runtime_id}")
