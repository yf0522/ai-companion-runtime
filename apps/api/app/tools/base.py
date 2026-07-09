from __future__ import annotations
from abc import ABC, abstractmethod
from pydantic import BaseModel


class ToolResult(BaseModel):
    tool_name: str
    status: str              # success / failed / timeout / needs_clarification
    data: dict | None = None
    display_text: str = ""
    latency_ms: int = 0


class ToolBase(ABC):
    name: str
    description: str
    parameters_schema: dict = {}

    @abstractmethod
    async def execute(self, params: dict) -> ToolResult:
        ...
