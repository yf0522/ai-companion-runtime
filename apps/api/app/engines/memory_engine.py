from __future__ import annotations

import logging

from app.engines.base import AnalyzerInput, BaseEngine, MemorySnapshot

logger = logging.getLogger(__name__)


class MemoryEngine(BaseEngine):
    """Memory recall engine. Reads L0 + L1 from Redis, L2 + L3 stubs for later phases."""

    async def analyze(self, input: AnalyzerInput) -> MemorySnapshot:
        working = []
        summary = None

        # L0: Working Memory (Redis)
        try:
            from app.storage.working_memory import get_working_memory
            working = await get_working_memory(input.session_id)
        except Exception as e:
            logger.warning(f"L0 read failed: {e}")

        # L1: Session Summary (Redis)
        try:
            from app.storage.working_memory import get_session_summary
            summary = await get_session_summary(input.session_id)
        except Exception as e:
            logger.warning(f"L1 read failed: {e}")

        # L2: User Profile (stub — Phase 4B)
        profile = {}

        # L3: Vector Memory (stub — Phase 4B)
        vectors = []

        return MemorySnapshot(
            working=working,
            summary=summary,
            profile=profile,
            vectors=vectors,
        )
