"""Shared tool registry — callable from harness, Pi bridge, and FC paths."""
from __future__ import annotations

from typing import Any

from app.tools.base import ToolBase, ToolResult


def build_default_tools() -> dict[str, ToolBase]:
    tools: dict[str, ToolBase] = {}
    from app.tools.weather_tool import WeatherTool
    from app.tools.calculator_tool import CalculatorTool

    tools["weather"] = WeatherTool()
    tools["calculator"] = CalculatorTool()
    try:
        from app.tools.search_tool import SearchTool

        tools["search"] = SearchTool()
    except ImportError:
        pass
    try:
        from app.tools.reminder_tool import ReminderTool

        tools["reminder"] = ReminderTool()
    except ImportError:
        pass
    from app.tools.caretask_tool import CareTaskTool
    from app.tools.memory_tool import MemoryTool

    tools["caretask"] = CareTaskTool()
    tools["memory"] = MemoryTool()
    return tools


_TOOLS: dict[str, ToolBase] | None = None


def get_tool_registry() -> dict[str, ToolBase]:
    global _TOOLS
    if _TOOLS is None:
        _TOOLS = build_default_tools()
    return _TOOLS


def get_tool(name: str) -> ToolBase | None:
    return get_tool_registry().get(name)


def list_tool_schemas() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in get_tool_registry().values():
        out.append(
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema or {"type": "object", "properties": {}},
            }
        )
    return out


async def execute_tool(name: str, params: dict) -> ToolResult:
    tool = get_tool(name)
    if tool is None:
        return ToolResult(
            tool_name=name,
            status="failed",
            display_text=f"未知工具：{name}",
            data={"reason": "unknown_tool"},
        )
    return await tool.execute(params)
