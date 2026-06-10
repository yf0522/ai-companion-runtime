from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

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


class RiskEngine(BaseEngine):
    def __init__(self):
        self._rules = _load_risk_rules()

    async def analyze(self, input: AnalyzerInput) -> RiskResult:
        message = input.message
        rules = self._rules.get("rules", {})

        # Check critical (highest priority, fastest path)
        critical = rules.get("critical", {})
        for kw in critical.get("keywords", []):
            if kw in message:
                return RiskResult(
                    level="critical",
                    category="self_harm",
                    confidence=0.95,
                    triggered_rules=[f"keyword:{kw}"],
                )

        # Check high
        high = rules.get("high", {})
        for kw in high.get("keywords", []):
            if kw in message:
                return RiskResult(
                    level="high",
                    category="self_harm",
                    confidence=0.85,
                    triggered_rules=[f"keyword:{kw}"],
                )
        for pattern in high.get("patterns", []):
            if re.search(pattern, message):
                return RiskResult(
                    level="high",
                    category="self_harm",
                    confidence=0.80,
                    triggered_rules=[f"pattern:{pattern}"],
                )

        # Check medium (rule: emotion_intensity > 0.85 AND valence < -0.7)
        # Medium check requires emotion data which we don't have here directly.
        # We approximate with keyword heuristics for very negative language.
        medium_keywords = [
            "绝望", "无助", "没有希望", "看不到未来", "太痛苦",
            "活着好累", "人生没意义",
        ]
        for kw in medium_keywords:
            if kw in message:
                return RiskResult(
                    level="medium",
                    category="sensitive",
                    confidence=0.6,
                    triggered_rules=[f"medium_keyword:{kw}"],
                )

        # Default: low risk
        return RiskResult(level="low", category="none", confidence=0.95)
