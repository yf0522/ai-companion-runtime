from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.engines.base import AnalyzerInput, BaseEngine, MemorySnapshot

logger = logging.getLogger(__name__)


def _normalize_user_id(user_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(user_id)
    except (ValueError, TypeError, AttributeError):
        try:
            return uuid.uuid5(uuid.NAMESPACE_DNS, str(user_id))
        except Exception:
            return None


class MemoryEngine(BaseEngine):
    """Memory recall: L0/L1 Redis + L2 profile + L3 important memories."""

    async def analyze(self, input: AnalyzerInput) -> MemorySnapshot:
        working = []
        summary = None
        profile: dict = {}
        vectors: list[dict] = []

        try:
            from app.storage.working_memory import get_working_memory

            working = await get_working_memory(input.session_id)
        except Exception as e:
            logger.warning(f"L0 read failed: {e}")

        try:
            from app.storage.working_memory import get_session_summary

            summary = await get_session_summary(input.session_id)
        except Exception as e:
            logger.warning(f"L1 read failed: {e}")

        db_user_id = _normalize_user_id(input.user_id)
        if db_user_id is not None:
            profile = await self._load_profile(db_user_id)
            vectors = await self._load_important_memories(db_user_id)

        return MemorySnapshot(
            working=working,
            summary=summary,
            profile=profile,
            vectors=vectors,
        )

    async def _load_profile(self, user_id: uuid.UUID) -> dict:
        try:
            from app.db.session import async_session
            from app.db.models import UserProfileModel

            async with async_session() as db:
                result = await db.execute(
                    select(UserProfileModel).where(UserProfileModel.user_id == user_id)
                )
                row = result.scalar_one_or_none()
                if row and isinstance(row.profile_json, dict):
                    return dict(row.profile_json)
        except Exception as e:
            logger.warning(f"L2 profile read failed: {e}")
        return {}

    async def _load_important_memories(self, user_id: uuid.UUID) -> list[dict]:
        try:
            from app.db.session import async_session
            from app.db.models import Memory

            async with async_session() as db:
                result = await db.execute(
                    select(Memory)
                    .where(Memory.user_id == user_id)
                    .order_by(Memory.importance_score.desc(), Memory.created_at.desc())
                    .limit(5)
                )
                rows = result.scalars().all()
                return [
                    {
                        "content": row.content,
                        "score": float(row.importance_score or 0.0),
                        "memory_type": row.memory_type,
                        "id": str(row.id),
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.warning(f"L3 memory read failed: {e}")
        return []
