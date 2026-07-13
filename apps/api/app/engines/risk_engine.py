from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from app.engines.base import AnalyzerInput, BaseEngine, RiskResult

logger = logging.getLogger(__name__)

_CLAUSE_BOUNDARY_RE = re.compile(r"[，,。；;！？!?\n]|(?:但是|不过|然而|可是|但|却)")
_NON_ASSERTED_CONTEXT_RE = re.compile(
    r"(?:新闻|报道).{0,8}(?:里|中)?(?:说|称|提到|写道|报道)|"
    r"(?:例子|例如|比如|举例|假设)"
)
_QUOTE_PAIRS = (("“", "”"), ("「", "」"), ("『", "』"), ('"', '"'), ("‘", "’"), ("'", "'"))


class RiskConfigurationError(RuntimeError):
    """Risk policy is unavailable or does not satisfy the runtime contract."""


def _risk_rules_path() -> Path:
    return Path(__file__).parent.parent / "config" / "risk_rules.yaml"


def _load_risk_rules() -> dict:
    path = _risk_rules_path()
    try:
        with open(path) as f:
            rules = yaml.safe_load(f)
    except Exception as e:
        raise RiskConfigurationError(f"Failed to load risk rules from {path}: {e}") from e

    if not isinstance(rules, dict) or not isinstance(rules.get("rules"), dict):
        raise RiskConfigurationError("Invalid risk rules: top-level 'rules' mapping is required")
    for level in ("critical", "high", "medium"):
        if level not in rules["rules"]:
            raise RiskConfigurationError(f"Invalid risk rules: missing '{level}' policy")
    return rules


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

    @staticmethod
    def _quote_spans(message: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        for opening, closing in _QUOTE_PAIRS:
            start = 0
            while (left := message.find(opening, start)) >= 0:
                right = message.find(closing, left + len(opening))
                if right < 0:
                    break
                spans.append((left, right + len(closing)))
                start = right + len(closing)
        return spans

    @staticmethod
    def _clause_start(message: str, position: int) -> int:
        start = 0
        for boundary in _CLAUSE_BOUNDARY_RE.finditer(message, 0, position):
            start = boundary.end()
        return start

    def _overlaps_safe_expression(self, message: str, start: int, end: int) -> bool:
        for safe in self._safe_patterns:
            safe_start = 0
            while (safe_idx := message.find(safe, safe_start)) >= 0:
                safe_end = safe_idx + len(safe)
                if safe_idx < end and start < safe_end:
                    return True
                safe_start = safe_end
        return False

    def _is_negated_span(self, message: str, start: int) -> bool:
        """Apply negation only within the match's clause and to its nearby target."""
        clause_start = self._clause_start(message, start)
        prefix = message[clause_start:start]
        nearest: tuple[int, str] | None = None
        for neg in (*self._negation_words, "不", "没"):
            idx = prefix.rfind(neg)
            if idx >= 0 and (nearest is None or idx > nearest[0]):
                nearest = (idx, neg)
        if nearest is None:
            return False
        neg_idx, neg = nearest
        between = prefix[neg_idx + len(neg):]
        # A nearby negator can govern a short noun/verb target (没有胸口疼、没有说想死),
        # but never crosses punctuation or adversative clause boundaries.
        return len(between) <= 5

    def _is_asserted_match(
        self,
        message: str,
        start: int,
        end: int,
        *,
        quote_spans: list[tuple[int, int]],
        pattern_match: bool = False,
    ) -> bool:
        if any(left <= start and end <= right for left, right in quote_spans):
            return False
        if self._overlaps_safe_expression(message, start, end):
            return False
        clause_start = self._clause_start(message, start)
        closed_quote_ends = [right for _, right in quote_spans if clause_start < right <= start]
        modality_start = clause_start
        if closed_quote_ends:
            after_quote = max(closed_quote_ends)
            if "我" in message[after_quote:start]:
                modality_start = after_quote
        clause_prefix = message[modality_start:start]
        if _NON_ASSERTED_CONTEXT_RE.search(clause_prefix):
            return False
        if pattern_match:
            matched = message[start:end]
            symptom_parts = list(re.finditer(
                r"(?:胸口|胸部|心口).{0,3}(?:疼|痛)|"
                r"(?:呼吸.{0,4}(?:困难|急促)|喘不上气|透不过气)",
                matched,
            ))
            if symptom_parts and any(
                self._is_negated_span(message, start + part.start())
                for part in symptom_parts
            ):
                return False
        return not self._is_negated_span(message, start)

    def _keyword_match(
        self,
        message: str,
        keyword: str,
        quote_spans: list[tuple[int, int]],
    ) -> bool:
        start = 0
        while (idx := message.find(keyword, start)) >= 0:
            end = idx + len(keyword)
            if self._is_asserted_match(message, idx, end, quote_spans=quote_spans):
                return True
            start = end
        return False

    def _pattern_match(
        self,
        message: str,
        pattern: str,
        quote_spans: list[tuple[int, int]],
    ) -> bool:
        return any(
            self._is_asserted_match(
                message, match.start(), match.end(), quote_spans=quote_spans,
                pattern_match=True,
            )
            for match in re.finditer(pattern, message)
        )

    async def analyze(self, input: AnalyzerInput) -> RiskResult:
        raw_message = input.message
        message = _normalize_text(raw_message)
        rules = self._rules.get("rules", {})
        quote_spans = self._quote_spans(message)

        # Critical: health emergency
        critical = rules.get("critical", {})
        for kw in critical.get("keywords", []):
            if self._keyword_match(message, kw, quote_spans):
                return RiskResult(
                    level="critical",
                    category=critical.get("category", "health_emergency"),
                    confidence=0.95,
                    triggered_rules=[f"keyword:{kw}"],
                )
        for pattern in critical.get("patterns", []):
            if self._pattern_match(message, pattern, quote_spans):
                return RiskResult(
                    level="critical",
                    category=critical.get("category", "health_emergency"),
                    confidence=0.95,
                    triggered_rules=[f"pattern:{pattern}"],
                )

        # High: sub-categories (scam / health)
        high = rules.get("high", {})
        for cat_name, cat_rules in high.get("categories", {}).items():
            category = "health_emergency" if cat_name == "health_concern" else cat_name
            for kw in cat_rules.get("keywords", []):
                if self._keyword_match(message, kw, quote_spans):
                    return RiskResult(
                        level="high",
                        category=category,
                        confidence=0.85,
                        triggered_rules=[f"keyword:{kw}"],
                    )
            for pattern in cat_rules.get("patterns", []):
                if self._pattern_match(message, pattern, quote_spans):
                    return RiskResult(
                        level="high",
                        category=category,
                        confidence=0.80,
                        triggered_rules=[f"pattern:{pattern}"],
                    )

        # Medium: emotional low
        medium = rules.get("medium", {})
        for kw in medium.get("keywords", []):
            if self._keyword_match(message, kw, quote_spans):
                return RiskResult(
                    level="medium",
                    category=medium.get("category", "emotional_low"),
                    confidence=0.6,
                    triggered_rules=[f"medium_keyword:{kw}"],
                )
        for pattern in medium.get("patterns", []):
            if self._pattern_match(message, pattern, quote_spans):
                return RiskResult(
                    level="medium",
                    category=medium.get("category", "emotional_low"),
                    confidence=0.7,
                    triggered_rules=[f"medium_pattern:{pattern}"],
                )

        # Default: low risk
        return RiskResult(level="low", category="none", confidence=0.95)
