from __future__ import annotations

import logging
import re

from app.engines.base import AnalyzerInput, BaseEngine, EmotionResult

logger = logging.getLogger(__name__)

# Emotion patterns with base intensity
EMOTION_RULES: list[dict] = [
    {
        "emotion": "fatigue",
        "patterns": [r"累", r"疲惫", r"好困", r"没力气", r"精疲力尽", r"好累", r"困死了", r"没精神"],
        "valence": -0.5,
        "base_intensity": 0.6,
    },
    {
        "emotion": "sadness",
        "patterns": [r"难过", r"伤心", r"哭", r"想哭", r"心痛", r"心疼", r"失去", r"离开"],
        "valence": -0.7,
        "base_intensity": 0.7,
    },
    {
        "emotion": "joy",
        "patterns": [r"开心", r"高兴", r"太棒了", r"哈哈", r"嘻嘻", r"好开心", r"太好了", r"耶"],
        "valence": 0.8,
        "base_intensity": 0.7,
    },
    {
        "emotion": "anxiety",
        "patterns": [r"焦虑", r"紧张", r"担心", r"害怕", r"恐惧", r"不安", r"慌", r"怕"],
        "valence": -0.6,
        "base_intensity": 0.65,
    },
    {
        "emotion": "anger",
        "patterns": [r"生气", r"愤怒", r"烦死了", r"气死了", r"讨厌", r"受不了", r"烦"],
        "valence": -0.8,
        "base_intensity": 0.7,
    },
    {
        "emotion": "fear",
        "patterns": [r"害怕", r"恐惧", r"吓", r"可怕", r"恐怖"],
        "valence": -0.7,
        "base_intensity": 0.6,
    },
]

# Intensity modifiers
INTENSITY_BOOSTERS = [r"很|非常|特别|超|太|极|好", r"死了|极了|透了|坏了"]
INTENSITY_DAMPENERS = [r"有点|稍微|略微|一点点"]

# Negation words that invert emotion (checked in a window before the keyword)
NEGATION_WORDS = ["不", "没", "没有", "别", "不要", "不是", "并不", "并没", "不太"]

# Patterns where an emotion word is used in a non-emotional context
CONTEXT_SAFE_PATTERNS = [
    re.compile(r"麻烦"),    # "麻烦你" contains "烦" but is polite
    re.compile(r"烦请"),    # polite request
    re.compile(r"不厌其烦"),  # idiom
    re.compile(r"心疼钱"),  # about money, not emotion
]


def _is_negated(message: str, match_start: int) -> bool:
    """Check if the emotion keyword at match_start is preceded by a negation word."""
    prefix_start = max(0, match_start - 4)
    prefix = message[prefix_start:match_start]
    return any(neg in prefix for neg in NEGATION_WORDS)


def _is_safe_context(message: str) -> bool:
    """Check if the message matches a known non-emotional context."""
    return any(p.search(message) for p in CONTEXT_SAFE_PATTERNS)


def _compute_trend(current_emotion: str, session_id: str) -> str:
    """Compute emotion trend from recent L0 working memory.

    Returns 'improving', 'declining', or 'stable'.
    This is a lightweight sync check — reads the last few stored emotion tags
    from Redis. Falls back to 'stable' if memory is unavailable.
    """
    # Trend computation requires async Redis access.
    # We store emotion tags in a side-channel key for fast trend lookup.
    # For now, return stable — trend is computed in analyze() with async access.
    return "stable"


class EmotionEngine(BaseEngine):
    async def analyze(self, input: AnalyzerInput) -> EmotionResult:
        message = input.message
        best_match = None
        best_score = 0.0

        # Skip if the message is a known safe context (e.g. "麻烦你")
        if _is_safe_context(message):
            return EmotionResult()

        for rule in EMOTION_RULES:
            match_count = 0
            negated = False
            for p in rule["patterns"]:
                m = re.search(p, message)
                if m:
                    # Check if this keyword is negated
                    if _is_negated(message, m.start()):
                        negated = True
                        continue
                    match_count += 1

            if match_count > 0 and not negated:
                score = rule["base_intensity"] + (match_count - 1) * 0.05
                if score > best_score:
                    best_score = score
                    best_match = rule

        if not best_match:
            return EmotionResult()  # neutral

        # Apply intensity modifiers
        intensity = best_match["base_intensity"]
        for booster in INTENSITY_BOOSTERS:
            if re.search(booster, message):
                intensity = min(1.0, intensity + 0.15)
                break
        for dampener in INTENSITY_DAMPENERS:
            if re.search(dampener, message):
                intensity = max(0.1, intensity - 0.2)
                break

        # Clamp
        intensity = min(1.0, max(0.0, intensity))

        # Compute trend from recent history
        trend = await self._compute_trend_async(
            best_match["emotion"], input.session_id,
        )

        return EmotionResult(
            emotion=best_match["emotion"],
            intensity=round(intensity, 2),
            valence=best_match["valence"],
            trend=trend,
        )

    async def _compute_trend_async(self, current_emotion: str, session_id: str) -> str:
        """Compute emotion trend by comparing with recent emotions in L0."""
        try:
            from app.storage.redis_client import get_redis

            r = await get_redis()
            key = f"emotion_history:{session_id}"

            # Push current emotion
            await r.rpush(key, current_emotion)
            await r.ltrim(key, -5, -1)  # Keep last 5
            await r.expire(key, 3600)  # 1 hour TTL

            # Read history
            history = await r.lrange(key, 0, -1)
            if len(history) < 2:
                return "stable"

            # Simple trend: compare negative emotion count in first vs second half
            negative_emotions = {"sadness", "anger", "anxiety", "fear", "fatigue"}
            prev = history[:-1]
            prev_neg = sum(1 for e in prev if e in negative_emotions)
            curr_is_neg = current_emotion in negative_emotions

            if curr_is_neg and prev_neg == 0:
                return "declining"
            elif not curr_is_neg and prev_neg > len(prev) // 2:
                return "improving"
            elif curr_is_neg and prev_neg >= len(prev) // 2:
                return "declining"
            else:
                return "stable"

        except Exception as e:
            logger.debug(f"Trend computation failed: {e}")
            return "stable"
