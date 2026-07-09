from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from app.engines.base import AnalyzerInput, BaseEngine, RiskResult

logger = logging.getLogger(__name__)


def _load_risk_rules() -> dict:
    path = Path(__file__).parent.parent / "config" / "risk_rules.yaml"
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load risk_rules.yaml: {e}")
        return {}


def _normalize_text(text: str) -> str:
    """Normalize text to improve keyword matching.

    Removes spaces/special chars between Chinese characters,
    lowercases, and strips common evasion tricks.
    """
    # Lowercase for English
    text = text.lower()
    # Remove spaces/dots/dashes between CJK characters (anti-splitting bypass)
    text = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', text)
    # Repeat for adjacent pairs missed on first pass
    text = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', text)
    # Remove zero-width and invisible unicode chars
    text = re.sub(r'[\u200b-\u200f\u2028-\u202f\ufeff]', '', text)
    return text


class RiskEngine(BaseEngine):
    def __init__(self):
        self._rules = _load_risk_rules()
        self._safe_patterns = self._rules.get("safe_context_patterns", [])
        self._negation_words = self._rules.get("negation_words", [])

    def _is_safe_context(self, message: str) -> bool:
        """Check if the message matches a known safe context (false positive)."""
        for safe in self._safe_patterns:
            if safe in message:
                return True
        return False

    def _is_negated(self, message: str, keyword: str) -> bool:
        """Check if a keyword is preceded by a negation word.

        e.g. "我没有想死" → "想死" is negated → not a real risk signal.
        "我不想死" → immediate 不 before 想死 → suppressed.
        But "我不想活了" → keyword is "不想活了" itself (YAML), not negated.
        """
        idx = message.find(keyword)
        if idx < 0:
            return False
        # Look at the 6 chars before the keyword for negation
        prefix_start = max(0, idx - 6)
        prefix = message[prefix_start:idx]
        for neg in self._negation_words:
            if neg in prefix:
                return True
            if idx >= len(neg) and message[idx - len(neg) : idx] == neg:
                return True
        # Immediate 不/没/别 before keyword (我不想死)
        if idx > 0 and message[idx - 1] in ("不", "没", "别"):
            return True
        return False

    async def analyze(self, input: AnalyzerInput) -> RiskResult:
        raw_message = input.message
        message = _normalize_text(raw_message)
        rules = self._rules.get("rules", {})

        # Fast path: safe context suppresses common false positives
        if self._is_safe_context(message):
            return RiskResult(level="low", category="none", confidence=0.9)

        # Critical: health emergency
        critical = rules.get("critical", {})
        for kw in critical.get("keywords", []):
            if kw in message and not self._is_negated(message, kw):
                return RiskResult(
                    level="critical",
                    category=critical.get("category", "health_emergency"),
                    confidence=0.95,
                    triggered_rules=[f"keyword:{kw}"],
                )

        # High: sub-categories (scam / health)
        high = rules.get("high", {})
        for cat_name, cat_rules in high.get("categories", {}).items():
            category = "health_emergency" if cat_name == "health_concern" else cat_name
            for kw in cat_rules.get("keywords", []):
                if kw in message and not self._is_negated(message, kw):
                    return RiskResult(
                        level="high",
                        category=category,
                        confidence=0.85,
                        triggered_rules=[f"keyword:{kw}"],
                    )
            for pattern in cat_rules.get("patterns", []):
                m = re.search(pattern, message)
                if m and not self._is_negated(message, m.group()):
                    return RiskResult(
                        level="high",
                        category=category,
                        confidence=0.80,
                        triggered_rules=[f"pattern:{pattern}"],
                    )

        # Medium: emotional low
        medium = rules.get("medium", {})
        for kw in medium.get("keywords", []):
            if kw in message and not self._is_negated(message, kw):
                return RiskResult(
                    level="medium",
                    category=medium.get("category", "emotional_low"),
                    confidence=0.6,
                    triggered_rules=[f"medium_keyword:{kw}"],
                )

        # Default: low risk
        return RiskResult(level="low", category="none", confidence=0.95)
