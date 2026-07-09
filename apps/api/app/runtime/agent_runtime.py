from __future__ import annotations

import asyncio
import logging
from typing import Protocol, runtime_checkable

from app.runtime.stream_manager import StreamManager

logger = logging.getLogger(__name__)

RUNTIME_HARNESS = "harness"
RUNTIME_PI_EXPERIMENTAL = "pi_experimental"

SUPPORTED_RUNTIMES: frozenset[str] = frozenset({RUNTIME_HARNESS, RUNTIME_PI_EXPERIMENTAL})
DEFAULT_RUNTIME = RUNTIME_HARNESS

_ALIASES: dict[str, str] = {
    "harness": RUNTIME_HARNESS,
    "standard": RUNTIME_HARNESS,
    "default": RUNTIME_HARNESS,
    "pi": RUNTIME_PI_EXPERIMENTAL,
    "pi_experimental": RUNTIME_PI_EXPERIMENTAL,
    "experimental": RUNTIME_PI_EXPERIMENTAL,
}


@runtime_checkable
class AgentRuntime(Protocol):
    """Pluggable agent execution path (production harness vs experimental Pi)."""

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
    """Factory for agent runtimes. Default is production AgentHarness."""
    runtime_id = normalize_runtime_name(name)
    if runtime_id == RUNTIME_HARNESS:
        from app.runtime.harness_runtime import HarnessRuntime

        return HarnessRuntime()
    if runtime_id == RUNTIME_PI_EXPERIMENTAL:
        from app.runtime.pi_runtime import PiExperimentalRuntime

        return PiExperimentalRuntime()
    raise ValueError(f"Unsupported runtime: {runtime_id}")
