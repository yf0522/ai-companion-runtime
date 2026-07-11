"""Utility tool — weather | calculator | search under one FC wire name."""
from __future__ import annotations

import logging

from app.tools.base import ToolBase, ToolResult
from app.tools.calculator_tool import CalculatorTool
from app.tools.search_tool import SearchTool
from app.tools.weather_tool import WeatherTool

logger = logging.getLogger(__name__)

_OPS = frozenset({"weather", "calculator", "search"})


class UtilityTool(ToolBase):
    """FC whitelist tool that dispatches to weather / calculator / search."""

    name = "utility"
    description = (
        "General utility: weather lookup, math calculator, or web search. "
        "Set op (or action) to weather | calculator | search."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "op": {
                "type": "string",
                "enum": ["weather", "calculator", "search"],
                "description": "Which utility operation to run",
            },
            "action": {
                "type": "string",
                "enum": ["weather", "calculator", "search"],
                "description": "Alias for op",
            },
            "query": {"type": "string", "description": "Natural language query"},
            "city": {"type": "string", "description": "City for weather"},
            "expression": {"type": "string", "description": "Math expression"},
        },
        "required": [],
    }

    def __init__(self) -> None:
        self._weather = WeatherTool()
        self._calculator = CalculatorTool()
        self._search = SearchTool()

    def _resolve_op(self, params: dict) -> str | None:
        raw = (params.get("op") or params.get("action") or params.get("operation") or "").strip().lower()
        if raw in _OPS:
            return raw
        # Infer from query heuristics when model omits op (post-FC normalizer may also set it).
        query = str(params.get("query") or "")
        if any(k in query for k in ("天气", "气温", "下雨", "温度")):
            return "weather"
        if any(k in query for k in ("算", "等于", "+", "-", "*", "/", "加", "减", "乘", "除")):
            return "calculator"
        if any(k in query for k in ("搜", "查一下", "搜索", "百度")):
            return "search"
        return None

    async def execute(self, params: dict) -> ToolResult:
        op = self._resolve_op(params)
        if op is None:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="请说明要用天气、计算还是搜索。",
                data={"reason": "missing_op"},
            )

        child_params = dict(params)
        if op == "weather" and params.get("city") and not child_params.get("query"):
            child_params["query"] = f"{params['city']}天气"
        if op == "calculator" and params.get("expression") and not child_params.get("query"):
            child_params["query"] = str(params["expression"])

        if op == "weather":
            result = await self._weather.execute(child_params)
        elif op == "calculator":
            result = await self._calculator.execute(child_params)
        else:
            result = await self._search.execute(child_params)

        data = dict(result.data or {})
        data["op"] = op
        data["action"] = f"utility_{op}"
        return ToolResult(
            tool_name=self.name,
            status=result.status,
            display_text=result.display_text,
            data=data,
            latency_ms=result.latency_ms,
        )
