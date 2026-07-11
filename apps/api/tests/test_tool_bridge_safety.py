"""Tool bridge production auth + Trace persistence."""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException


def test_token_required_in_production(monkeypatch):
    from app.api import tool_execute as te

    monkeypatch.delenv("REQUIRE_TOOL_BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TOOL_BRIDGE_TOKEN", raising=False)
    assert te._token_required() is True
    assert te._bridge_token_ok(None, None) is False


def test_token_not_required_in_development(monkeypatch):
    from app.api import tool_execute as te

    monkeypatch.delenv("REQUIRE_TOOL_BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("TOOL_BRIDGE_TOKEN", raising=False)
    assert te._token_required() is False
    assert te._bridge_token_ok(None, None) is True


def test_require_tool_bridge_token_flag(monkeypatch):
    from app.api import tool_execute as te

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("REQUIRE_TOOL_BRIDGE_TOKEN", "1")
    monkeypatch.delenv("TOOL_BRIDGE_TOKEN", raising=False)
    assert te._token_required() is True
    assert te._bridge_token_ok(None, None) is False


def test_valid_token_accepted(monkeypatch):
    from app.api import tool_execute as te

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TOOL_BRIDGE_TOKEN", "secret-bridge")
    assert te._bridge_token_ok(None, "secret-bridge") is True
    assert te._bridge_token_ok("Bearer secret-bridge", None) is True
    assert te._bridge_token_ok(None, "wrong") is False


@pytest.mark.asyncio
async def test_tool_execute_rejects_when_prod_token_missing(monkeypatch):
    from app.api.tool_execute import ToolExecuteRequest, tool_execute

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TOOL_BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("REQUIRE_TOOL_BRIDGE_TOKEN", raising=False)

    with pytest.raises(HTTPException) as exc:
        await tool_execute(
            ToolExecuteRequest(tool_name="caretask", params={"action": "list"}),
            authorization=None,
            x_tool_bridge_token=None,
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_tool_execute_records_trace_tool_call(monkeypatch):
    from app.api.tool_execute import ToolExecuteRequest, tool_execute
    from app.observability import trace_service as ts_mod

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("TOOL_BRIDGE_TOKEN", raising=False)

    recorded = {}

    class _TS:
        async def record_tool_call(self, **kwargs):
            recorded.update(kwargs)

    monkeypatch.setattr(ts_mod, "TraceService", _TS)

    async def fake_execute(name, params):
        from app.tools.base import ToolResult

        return ToolResult(
            tool_name=name,
            status="success",
            display_text="ok",
            data={"action": "caretask_list", "tasks": []},
        )

    monkeypatch.setattr("app.api.tool_execute.execute_tool", fake_execute)

    uid = str(uuid.uuid4())
    resp = await tool_execute(
        ToolExecuteRequest(
            tool_name="caretask",
            params={"action": "list"},
            user_id=uid,
            trace_id="tr-bridge-1",
        ),
        authorization=None,
        x_tool_bridge_token=None,
    )
    assert resp.status == "success"
    assert recorded["trace_id"] == "tr-bridge-1"
    assert recorded["tool_name"] == "caretask"
    assert recorded["status"] == "success"


@pytest.mark.asyncio
async def test_contact_tool_uses_trusted_runtime_context(monkeypatch):
    from app.api.tool_execute import ToolExecuteRequest, tool_execute
    from app.tools.base import ToolResult

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("TOOL_BRIDGE_TOKEN", raising=False)

    captured: dict = {}

    async def fake_execute(name, params):
        captured["name"] = name
        captured["params"] = params
        return ToolResult(
            tool_name=name,
            status="success",
            display_text="求助请求已记录，送达状态还在确认。",
            data={"action": "contact_help_request", "delivery_status": "queued"},
        )

    monkeypatch.setattr("app.api.tool_execute.execute_tool", fake_execute)
    trusted_user = str(uuid.uuid4())
    trusted_session = str(uuid.uuid4())

    response = await tool_execute(
        ToolExecuteRequest(
            tool_name="contact",
            params={
                "action": "request_contact",
                "query": "请家人联系我",
                "user_id": str(uuid.uuid4()),
                "session_id": "model-session",
                "trace_id": "model-trace",
                "recipient": "attacker@example.com",
                "provider": "model-provider",
                "risk_level": "critical",
            },
            user_id=trusted_user,
            session_id=trusted_session,
            trace_id="trusted-trace",
        ),
        authorization=None,
        x_tool_bridge_token=None,
    )

    assert response.status == "success"
    assert captured["name"] == "contact"
    assert captured["params"]["user_id"] == trusted_user
    assert captured["params"]["session_id"] == trusted_session
    assert captured["params"]["trace_id"] == "trusted-trace"
    assert "recipient" not in captured["params"]
    assert "provider" not in captured["params"]
    assert "risk_level" not in captured["params"]
