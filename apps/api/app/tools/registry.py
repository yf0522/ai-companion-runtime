"""Shared tool registry — callable from Pi bridge and FC paths.

Production FC whitelist (ADR-002): caretask | memory | utility exactly.
Legacy top-level weather/calculator/search/reminder are folded / mapped.
"""
from __future__ import annotations

from typing import Any

from app.tools.base import ToolBase, ToolResult

# Wire names exposed to LLM / schemas endpoint.
FC_WHITELIST: frozenset[str] = frozenset({"caretask", "memory", "utility"})

# Legacy names → (canonical tool, param merge). Post-FC / bridge normalizers.
_LEGACY_TOOL_MAP: dict[str, tuple[str, dict[str, Any]]] = {
    "weather": ("utility", {"op": "weather"}),
    "calculator": ("utility", {"op": "calculator"}),
    "search": ("utility", {"op": "search"}),
    "reminder": ("caretask", {}),
}


def build_default_tools() -> dict[str, ToolBase]:
    from app.tools.caretask_tool import CareTaskTool
    from app.tools.memory_tool import MemoryTool
    from app.tools.utility_tool import UtilityTool

    return {
        "caretask": CareTaskTool(),
        "memory": MemoryTool(),
        "utility": UtilityTool(),
    }


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
    for name in ("caretask", "memory", "utility"):
        tool = get_tool(name)
        if tool is None:
            continue
        out.append(
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema or {"type": "object", "properties": {}},
            }
        )
    return out


def normalize_tool_request(name: str, params: dict | None) -> tuple[str, dict]:
    """Map legacy tool names onto the 3-tool whitelist (post-FC / bridge)."""
    merged = dict(params or {})
    key = (name or "").strip().lower()
    if key in FC_WHITELIST:
        return key, merged
    if key in _LEGACY_TOOL_MAP:
        canonical, extra = _LEGACY_TOOL_MAP[key]
        for k, v in extra.items():
            merged.setdefault(k, v)
        if key == "reminder" and "action" not in merged:
            # Reminder utterances → caretask create/list via query grounding.
            merged.setdefault("query", merged.get("query") or "")
        return canonical, merged
    return key, merged


async def execute_tool(name: str, params: dict) -> ToolResult:
    canonical, merged = normalize_tool_request(name, params)
    if canonical not in FC_WHITELIST:
        return ToolResult(
            tool_name=name,
            status="failed",
            display_text=f"未知工具：{name}",
            data={"reason": "unknown_tool", "hint": "use caretask|memory|utility"},
        )
    tool = get_tool(canonical)
    if tool is None:
        return ToolResult(
            tool_name=canonical,
            status="failed",
            display_text=f"未知工具：{canonical}",
            data={"reason": "unknown_tool"},
        )
    result = await tool.execute(merged)
    # Preserve wire name as whitelist tool.
    if result.tool_name != canonical:
        result = ToolResult(
            tool_name=canonical,
            status=result.status,
            display_text=result.display_text,
            data=result.data,
            latency_ms=result.latency_ms,
        )
    return result
