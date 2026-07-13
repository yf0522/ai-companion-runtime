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
    query: str | None = None
    idempotency_key: str | None = None
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
        from app.observability.trace_service import TraceService, sanitize_tool_evidence

        await TraceService().record_tool_call(
            trace_id=trace_id,
            tool_name=tool_name,
            input_json=sanitize_tool_evidence(input_json),
            output_json=sanitize_tool_evidence(output_json),
            status=status,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        logger.error(
            "Bridge tool trace failed tool=%s error_class=%s code=bridge_tool_trace_failed",
            tool_name,
            type(exc).__name__,
        )


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
    # Params are model-controlled. Identity and correlation values come only
    # from the trusted bridge envelope when present and can never be overridden.
    for key in (
        "user_id",
        "session_id",
        "trace_id",
        "idempotency_key",
        "risk_blocked",
        "risk_level",
        "query",
    ):
        params.pop(key, None)
    if body.user_id:
        params["user_id"] = body.user_id
    if body.session_id:
        params["session_id"] = body.session_id
    if body.trace_id:
        params["trace_id"] = body.trace_id
    if body.query is not None:
        params["query"] = body.query
    if body.idempotency_key is not None:
        params["idempotency_key"] = body.idempotency_key
    requested_action = str(params.get("action") or "").strip().lower()
    trusted_query = str(body.query or "").strip()
    mutation_requested = False
    if body.tool_name == "caretask":
        from app.tools.caretask_batch import (
            classify_caretask_speech_act,
            detect_compound_caretask,
            plan_caretask_batch,
        )

        plan = plan_caretask_batch(trusted_query) if detect_compound_caretask(trusted_query) else None
        speech_act = classify_caretask_speech_act(trusted_query)
        if plan is not None and plan.status == "planned":
            params["action"] = "batch"
            mutation_requested = any(action.action != "list" for action in plan.actions)
        elif speech_act.authorized and speech_act.action is not None:
            params["action"] = speech_act.action
            mutation_requested = speech_act.action != "list"
        elif speech_act.action is None and requested_action not in {"", "list"}:
            # Model parameters cannot supply missing user authorization.
            raise HTTPException(status_code=400, detail="side_effect_not_authorized")
    elif body.tool_name == "memory":
        from app.tools.memory_tool import is_explicit_memory_note

        mutation_requested = is_explicit_memory_note(trusted_query)
        params["action"] = "note" if mutation_requested else "recall"
    elif body.tool_name == "contact":
        from app.tools.contact_tool import is_explicit_family_contact_request

        if not is_explicit_family_contact_request(trusted_query):
            raise HTTPException(status_code=400, detail="side_effect_not_authorized")
        params["action"] = "request_contact"
        mutation_requested = True
    if mutation_requested:
        required = {
            "user_id": body.user_id,
            "session_id": body.session_id,
            "trace_id": body.trace_id,
            "query": body.query,
            "idempotency_key": body.idempotency_key,
        }
        if any(value is None or str(value).strip() == "" for value in required.values()):
            raise HTTPException(status_code=400, detail="mutation_requires_trusted_context")
    if body.tool_name == "contact":
        # Contact requests are side effects. Never let model-provided params
        # override the authenticated runtime context or choose a recipient.
        for key in ("recipient", "provider"):
            params.pop(key, None)
    # Propagate risk context so domain tools (e.g. memory) can empty/skip on crisis.
    params["risk_blocked"] = bool(body.risk_blocked)
    if body.risk_level is not None:
        params["risk_level"] = body.risk_level

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
        input_json=params,
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
