from __future__ import annotations

import logging
import re

from app.engines.base import AnalyzerInput, BaseEngine, IntentResult

logger = logging.getLogger(__name__)

# Tool keyword mappings — each entry has patterns and negative contexts
# A tool is only triggered if a pattern matches AND no negative context matches.
# Regex TOOL_RULES are FALLBACK-ONLY tool selection (harness when model FC unavailable).
# Prefer model/Pi function-calling; do not treat these as the primary orchestration path.
TOOL_RULES: dict[str, dict] = {
    "weather": {
        "patterns": [r"天气(?:怎么样|如何|预报|情况)", r"气温多少", r"会不会下雨", r"会不会下雪", r"温度多少"],
        "negative": [r"天气真好", r"天气不错", r"天气好"],  # describing weather, not querying
    },
    "search": {
        "patterns": [r"搜索一下", r"搜一下", r"查一下", r"帮我[找查搜]", r"百度一下", r"谷歌一下"],
        "negative": [],
    },
    "calculator": {
        "patterns": [r"计算一下", r"算一下", r"帮我算", r"\d+\s*[+\-*/×÷]\s*\d+", r"等于多少"],
        "negative": [],
    },
    "caretask": {
        "patterns": [
            r"吃药", r"吃.{1,12}药", r"服药", r"服用.{1,12}药", r"降压药", r"降糖药", r"量血压", r"测血糖",
            r"复诊", r"预约.*医院", r"看病",
            r"照护任务", r"用药任务",
            r"吃完了", r"已经吃", r"晚点再吃", r"等会儿再吃",
            r"我的.*任务", r"待办.*药",
        ],
        "negative": [r"吃药真麻烦"],  # venting, not a task request
    },
    "reminder": {
        "patterns": [
            r"提醒我", r"别忘了.{2,}", r"记得.{2,}点",
            r"定个闹钟", r"定时提醒", r"设置.*提醒",
            r"\d+分钟.*叫", r"叫.{1,3}起床",
            r"计时(?:器|\d+)", r"倒计时",
            r"(?:早上|下午|晚上|明天|今天)?\d{1,2}点[叫喊呼唤]",
            r"帮我定.{1,6}(?:闹钟|提醒|计时)", r"闹钟",
            # Snooze / 二次提醒 (demo: 晚点再吃) — also covered by caretask; reminder kept for timers
            r"晚点再吃", r"等会儿再吃", r"一会儿再吃",
            r"过一会儿再提醒", r"再提醒我", r"推迟.*提醒",
            r"半小时后再说", r"\d+\s*分钟后再", r"晚点再提醒",
        ],
        "negative": [],
    },
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
    r"帮我[^\s]{1,10}",  # "帮我" followed by an action
    r"怎么做|怎么弄|如何",
    r"请问|问一下|想知道",
]


class IntentEngine(BaseEngine):
    async def analyze(self, input: AnalyzerInput) -> IntentResult:
        message = input.message
        tool_needs = []
        secondary_intents = []

        # Fallback-only regex tool selection (demoted from primary orchestration).
        for tool, rule in TOOL_RULES.items():
            # Check if any negative context matches first
            if any(re.search(neg, message) for neg in rule.get("negative", [])):
                continue
            # Then check positive patterns
            for pattern in rule["patterns"]:
                if re.search(pattern, message):
                    tool_needs.append(tool)
                    secondary_intents.append(tool)
                    break

        # Prefer CareTask over Reminder when both match care-domain utterances.
        if "caretask" in tool_needs and "reminder" in tool_needs:
            tool_needs = [t for t in tool_needs if t != "reminder"]
            secondary_intents = [t for t in secondary_intents if t != "reminder"]

        # Detect primary intent
        has_emotion = any(
            re.search(p, message) for p in EMOTIONAL_PATTERNS
        )
        has_task = bool(tool_needs) or any(
            re.search(p, message) for p in TASK_PATTERNS
        )

        if has_emotion and has_task:
            # When both present: if there are tool_needs, task takes priority
            # (user wants something done AND is emotional about it)
            primary_intent = "task" if tool_needs else "emotional_support"
        elif has_emotion:
            primary_intent = "emotional_support"
        elif has_task:
            primary_intent = "task"
        elif re.search(r"[?？]", message) and len(message) > 3:
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
