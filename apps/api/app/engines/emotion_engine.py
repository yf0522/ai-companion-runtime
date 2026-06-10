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


class EmotionEngine(BaseEngine):
    async def analyze(self, input: AnalyzerInput) -> EmotionResult:
        message = input.message
        best_match = None
        best_score = 0.0

        for rule in EMOTION_RULES:
            match_count = sum(
                1 for p in rule["patterns"] if re.search(p, message)
            )
            if match_count > 0:
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

        return EmotionResult(
            emotion=best_match["emotion"],
            intensity=round(intensity, 2),
            valence=best_match["valence"],
            trend="stable",  # Trend requires L0 history, will be added in Phase 4
        )
