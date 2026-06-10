from __future__ import annotations

from app.engines.base import (
    IntentResult, EmotionResult, MemorySnapshot, PersonalityConfig,
)


class PromptBuilder:
    """Assembles the final prompt from engine outputs."""

    def build(
        self,
        user_message: str,
        intent: IntentResult,
        emotion: EmotionResult,
        personality: PersonalityConfig,
        memory: MemorySnapshot,
        tool_results: list[dict] | None = None,
    ) -> list[dict]:
        system_parts = []

        # Base role
        system_parts.append(f"你是用户的长期 AI Companion。你的风格：{personality.tone}。")

        # Personality rules
        if personality.style_rules:
            rules = "；".join(personality.style_rules)
            system_parts.append(f"行为准则：{rules}。")

        # Emotion context
        if emotion.emotion != "neutral":
            system_parts.append(
                f"用户当前情绪：{emotion.emotion}，强度 {emotion.intensity:.1f}，"
                f"趋势 {emotion.trend}。"
            )

        # Intent context
        if intent.primary_intent:
            system_parts.append(f"用户意图：{intent.primary_intent}。")
            if intent.secondary_intents:
                system_parts.append(f"次要意图：{'、'.join(intent.secondary_intents)}。")

        # Avoid phrases
        if personality.avoid_phrases:
            system_parts.append(f"禁止使用：{'、'.join(personality.avoid_phrases)}。")

        # Encourage patterns
        if personality.encourage_patterns:
            system_parts.append(f"鼓励使用：{'、'.join(personality.encourage_patterns)}。")

        # Max length
        if personality.max_length:
            system_parts.append(f"回复不超过 {personality.max_length} 字。")

        # Memory context
        if memory.summary:
            system_parts.append(f"\n当前会话摘要：{memory.summary}")

        if memory.profile:
            profile_str = "、".join(f"{k}={v}" for k, v in memory.profile.items() if v)
            if profile_str:
                system_parts.append(f"用户画像：{profile_str}。")

        if memory.vectors:
            mem_texts = [m.get("content", "") for m in memory.vectors[:5] if m.get("content")]
            if mem_texts:
                system_parts.append(f"\n相关记忆：\n" + "\n".join(f"- {t}" for t in mem_texts))

        # Assemble messages
        messages = [{"role": "system", "content": "\n".join(system_parts)}]

        # Add recent messages from working memory
        for msg in memory.working[-10:]:  # Last 10 from L0
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        # Tool results
        if tool_results:
            tool_text = "\n".join(
                f"工具 {t.get('tool_name', '?')} 结果：{t.get('display_text', '')}"
                for t in tool_results
            )
            messages.append({"role": "system", "content": f"工具调用结果：\n{tool_text}"})

        # Current user message
        messages.append({"role": "user", "content": user_message})

        # Response instructions
        messages.append({
            "role": "system",
            "content": "要求：1. 先承接情绪 2. 再完成任务 3. 不像客服 4. 不过度心理咨询化 5. 结尾自然追问 6. 绝对禁止用小括号写动作或旁白，如（笑）（递茶）（轻声说），直接用文字表达",
        })

        return messages
