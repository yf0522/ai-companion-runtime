from __future__ import annotations

import logging

from app.engines.base import AnalyzerInput, BaseEngine, UserProfile

logger = logging.getLogger(__name__)


class ReflectionEngine(BaseEngine):
    """Analyzes recent conversations and updates user profile.
    Full implementation in Phase 6. This is the interface stub."""

    async def analyze(self, input: AnalyzerInput) -> UserProfile:
        """Placeholder — returns empty profile."""
        return UserProfile(user_id=input.user_id)

    async def reflect(
        self,
        user_id: str,
        recent_messages: list[dict],
        current_profile: dict,
    ) -> dict:
        """Run reflection to update user profile.
        Full implementation will use a model to analyze patterns.
        Returns updated profile_json."""
        logger.debug(f"Reflection stub for user {user_id}")
        return current_profile
