from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from app.engines.base import (
    EmotionResult, IntentResult, PersonalityConfig, UserProfile,
)

logger = logging.getLogger(__name__)


def _load_personality_config() -> dict:
    path = Path(__file__).parent.parent / "config" / "personality.yaml"
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Failed to load personality.yaml: {e}")
        return {}


class PersonalityEngine:
    def __init__(self):
        self._config = _load_personality_config()

    async def adapt(
        self,
        emotion: EmotionResult,
        intent: Optional[IntentResult] = None,
        profile: Optional[UserProfile] = None,
    ) -> PersonalityConfig:
        """Build PersonalityConfig by overlaying adaptation rules on base personality."""
        base = self._config.get("base_personality", {})
        adaptations = self._config.get("adaptation", {})

        # Start with base
        tone = base.get("tone", "温暖、自然、不刻意")
        style_rules = list(base.get("style_rules", []))
        max_length = None
        avoid_phrases = []
        encourage_patterns = []

        # Find matching adaptation
        adaptation = self._match_adaptation(emotion, intent, adaptations)

        if adaptation:
            tone = adaptation.get("tone_shift", tone)
            max_length = adaptation.get("max_length")
            avoid_phrases = adaptation.get("avoid", [])
            encourage_patterns = adaptation.get("encourage", [])

        return PersonalityConfig(
            tone=tone,
            style_rules=style_rules,
            max_length=max_length,
            avoid_phrases=avoid_phrases,
            encourage_patterns=encourage_patterns,
        )

    def _match_adaptation(
        self,
        emotion: EmotionResult,
        intent: Optional[IntentResult],
        adaptations: dict,
    ) -> Optional[dict]:
        """Find the best matching adaptation rule."""
        # Task mode takes precedence if intent is task
        if intent and intent.primary_intent == "task":
            if "task_mode" in adaptations:
                return adaptations["task_mode"]

        # Match by emotion + intensity
        emotion_key = f"{emotion.emotion}_high"
        if emotion.intensity > 0.7 and emotion_key in adaptations:
            return adaptations[emotion_key]

        # No match
        return None
