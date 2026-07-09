"""HTTP bridge for Pi sidecar (and other runtimes) to execute shared tools."""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.tools.base import ToolResult
from app.tools.registry import execute_tool, list_tool_schemas

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tools"])


class ToolExecuteRequest(BaseModel):
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None
    session_id: str | None = None
    trace_id: str | None = None
    risk_blocked: bool = False
    risk_level: str | None = None


class ToolExecuteResponse(BaseModel):
    tool_name: str
    status: str
    display_text: str = ""
    data: dict[str, Any] | None = None
    latency_ms: int = 0


def _bridge_token_ok(authorization: str | None, x_tool_bridge_token: str | None) -> bool:
    expected = os.environ.get("TOOL_BRIDGE_TOKEN", "").strip()
    if not expected:
        # Dev default: allow local sidecar without shared secret.
        return True
    if x_tool_bridge_token and x_tool_bridge_token == expected:
        return True
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ").strip() == expected
    return False


@router.get("/tools/schemas")
async def tool_schemas(
    authorization: str | None = Header(default=None),
    x_tool_bridge_token: str | None = Header(default=None),
) -> dict[str, Any]:
    if not _bridge_token_ok(authorization, x_tool_bridge_token):
        raise HTTPException(status_code=401, detail="invalid_bridge_token")
    return {"tools": list_tool_schemas()}


@router.post("/tools/execute", response_model=ToolExecuteResponse)
async def tool_execute(
    body: ToolExecuteRequest,
    authorization: str | None = Header(default=None),
    x_tool_bridge_token: str | None = Header(default=None),
) -> ToolExecuteResponse:
    if not _bridge_token_ok(authorization, x_tool_bridge_token):
        raise HTTPException(status_code=401, detail="invalid_bridge_token")

    if body.risk_blocked or (body.risk_level or "").lower() in {"high", "critical"}:
        return ToolExecuteResponse(
            tool_name=body.tool_name,
            status="failed",
            display_text="风险拦截：当前不能执行工具",
            data={"reason": "risk_blocked", "risk_level": body.risk_level},
            latency_ms=0,
        )

    params = dict(body.params or {})
    if body.user_id and "user_id" not in params:
        params["user_id"] = body.user_id
    if body.session_id and "session_id" not in params:
        params["session_id"] = body.session_id
    if body.trace_id and "trace_id" not in params:
        params["trace_id"] = body.trace_id

    start = time.monotonic()
    result: ToolResult = await execute_tool(body.tool_name, params)
    latency = int((time.monotonic() - start) * 1000)
    result.latency_ms = latency
    logger.info(
        "tool_bridge execute name=%s status=%s latency=%sms",
        body.tool_name,
        result.status,
        latency,
    )
    return ToolExecuteResponse(
        tool_name=result.tool_name,
        status=result.status,
        display_text=result.display_text,
        data=result.data,
        latency_ms=latency,
    )
