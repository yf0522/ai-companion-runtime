from __future__ import annotations

from app.engines.base import RiskResult


class ResponsePolicy:
    """Determines response constraints based on risk and context."""

    def should_block(self, risk: RiskResult) -> bool:
        return risk.level in ("critical", "high")

    def should_block_tools(self, risk: RiskResult) -> bool:
        return risk.level in ("critical", "high")

    def should_add_care(self, risk: RiskResult) -> bool:
        return risk.level == "medium"
