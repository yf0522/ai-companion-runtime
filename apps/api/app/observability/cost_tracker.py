from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Cost per 1K tokens in cents (approximate)
COST_TABLE = {
    "qwen-plus": {"prompt": 0.4, "completion": 1.2},
    "qwen-turbo": {"prompt": 0.1, "completion": 0.3},
    "deepseek-chat": {"prompt": 0.07, "completion": 0.28},
    "gpt-4o": {"prompt": 0.25, "completion": 1.0},
    "gpt-4o-mini": {"prompt": 0.015, "completion": 0.06},
}


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate cost in cents for a model call."""
    rates = COST_TABLE.get(model, {"prompt": 0.1, "completion": 0.3})
    cost = (
        (prompt_tokens / 1000) * rates["prompt"]
        + (completion_tokens / 1000) * rates["completion"]
    )
    return round(cost, 4)
