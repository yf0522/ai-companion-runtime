from __future__ import annotations

import logging
import re

from app.engines.base import AnalyzerInput, BaseEngine, IntentResult

logger = logging.getLogger(__name__)

# Tool keyword mappings
TOOL_PATTERNS: dict[str, list[str]] = {
    "weather": [r"天气", r"气温", r"下雨", r"下雪", r"晴", r"多云", r"温度"],
    "search": [r"搜索", r"搜一下", r"查一下", r"百度", r"谷歌", r"帮我找"],
    "calculator": [r"计算", r"算一下", r"\d+\s*[+\-*/]\s*\d+", r"等于多少"],
    "reminder": [r"提醒我", r"别忘了", r"记得.*点", r"闹钟", r"定时"],
}

# Emotional keywords
EMOTIONAL_PATTERNS = [
    r"累|疲惫|好困|没力气|精疲力尽",
    r"难过|伤心|哭|想哭|心痛|心疼",
    r"开心|高兴|太棒了|哈哈|嘻嘻|好开心",
    r"焦虑|紧张|担心|害怕|恐惧|不安",
    r"生气|愤怒|烦死了|气死了|讨厌",
    r"孤独|寂寞|一个人|没人",
    r"压力|崩溃|受不了|扛不住",
]

# Task intent keywords
TASK_PATTERNS = [
    r"帮我|帮忙|麻烦你",
    r"怎么做|怎么弄|如何",
    r"请问|问一下|想知道",
]


class IntentEngine(BaseEngine):
    async def analyze(self, input: AnalyzerInput) -> IntentResult:
        message = input.message
        tool_needs = []
        secondary_intents = []

        # Detect tool needs
        for tool, patterns in TOOL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, message):
                    tool_needs.append(tool)
                    secondary_intents.append(tool)
                    break

        # Detect primary intent
        has_emotion = any(
            re.search(p, message) for p in EMOTIONAL_PATTERNS
        )
        has_task = bool(tool_needs) or any(
            re.search(p, message) for p in TASK_PATTERNS
        )

        if has_emotion and has_task:
            primary_intent = "emotional_support"
            # Emotion is primary, task is secondary
        elif has_emotion:
            primary_intent = "emotional_support"
        elif has_task:
            primary_intent = "task"
        elif "?" in message or "？" in message:
            primary_intent = "question"
        else:
            primary_intent = "chitchat"

        confidence = 0.9 if (has_emotion or has_task) else 0.6

        return IntentResult(
            primary_intent=primary_intent,
            secondary_intents=secondary_intents,
            confidence=confidence,
            tool_needs=tool_needs,
        )
