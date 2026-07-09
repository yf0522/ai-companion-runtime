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


def _token_required() -> bool:
    """Require TOOL_BRIDGE_TOKEN in production / when explicitly forced.

    Local/dev may leave the token unset for an open bridge. Public/prod must not.
    """
    if os.environ.get("REQUIRE_TOOL_BRIDGE_TOKEN", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return True
    app_env = (
        os.environ.get("APP_ENV") or os.environ.get("ENV") or ""
    ).strip().lower()
    return app_env in {"production", "prod"}


def _bridge_token_ok(authorization: str | None, x_tool_bridge_token: str | None) -> bool:
    expected = os.environ.get("TOOL_BRIDGE_TOKEN", "").strip()
    if not expected:
        if _token_required():
            return False
        # Dev default: allow local sidecar without shared secret.
        return True
    if x_tool_bridge_token and x_tool_bridge_token == expected:
        return True
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ").strip() == expected
    return False


async def _record_bridge_tool_call(
    *,
    trace_id: str | None,
    tool_name: str,
    input_json: dict,
    output_json: dict | None,
    status: str,
    latency_ms: int,
) -> None:
    """Best-effort Trace persistence for Pi / bridge path (parity with harness)."""
    if not trace_id:
        return
    try:
        from app.observability.trace_service import TraceService

        await TraceService().record_tool_call(
            trace_id=trace_id,
            tool_name=tool_name,
            input_json=input_json,
            output_json=output_json,
            status=status,
            latency_ms=latency_ms,
        )
    except Exception as e:
        logger.error("Failed to persist bridge tool call for %s: %s", tool_name, e)


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
        resp = ToolExecuteResponse(
            tool_name=body.tool_name,
            status="failed",
            display_text="风险拦截：当前不能执行工具",
            data={"reason": "risk_blocked", "risk_level": body.risk_level},
            latency_ms=0,
        )
        await _record_bridge_tool_call(
            trace_id=body.trace_id,
            tool_name=body.tool_name,
            input_json={"params": body.params, "risk_level": body.risk_level},
            output_json={"status": resp.status, "display_text": resp.display_text, "data": resp.data},
            status="failed",
            latency_ms=0,
        )
        return resp

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
    await _record_bridge_tool_call(
        trace_id=body.trace_id,
        tool_name=result.tool_name,
        input_json={
            "query": params.get("query"),
            "user_id": params.get("user_id"),
            "session_id": params.get("session_id"),
            "action": params.get("action"),
        },
        output_json={
            "status": result.status,
            "display_text": result.display_text,
            "data": result.data,
        },
        status=result.status,
        latency_ms=latency,
    )
    return ToolExecuteResponse(
        tool_name=result.tool_name,
        status=result.status,
        display_text=result.display_text,
        data=result.data,
        latency_ms=latency,
    )
