"""Tool bridge production auth + Trace persistence."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

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
    secret = "sk-private https://provider.example/raw transcript"
    resp = await tool_execute(
        ToolExecuteRequest(
            tool_name="caretask",
            params={"action": "list", "notes": secret, "query": "model override"},
            user_id=uid,
            trace_id="tr-bridge-1",
            query=secret,
        ),
        authorization=None,
        x_tool_bridge_token=None,
    )
    assert resp.status == "success"
    assert recorded["trace_id"] == "tr-bridge-1"
    assert recorded["tool_name"] == "caretask"
    assert recorded["status"] == "success"
    assert secret not in str(recorded)
    assert recorded["input_json"]["content_redacted"] is True
    assert recorded["input_json"]["action"] == "list"


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
            query="请家人联系我",
            idempotency_key="trusted-trace",
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


@pytest.mark.asyncio
async def test_caretask_batch_cannot_override_trusted_cross_user_context(monkeypatch):
    from app.api.tool_execute import ToolExecuteRequest, tool_execute
    from app.tools.base import ToolResult

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("TOOL_BRIDGE_TOKEN", raising=False)
    captured: dict = {}

    async def fake_execute(name, params):
        captured.update(params)
        return ToolResult(tool_name=name, status="success", display_text="ok", data={})

    monkeypatch.setattr("app.api.tool_execute.execute_tool", fake_execute)
    trusted_user = str(uuid.uuid4())
    await tool_execute(
        ToolExecuteRequest(
            tool_name="caretask",
            params={
                "action": "batch",
                "user_id": str(uuid.uuid4()),
                "session_id": "attacker-session",
                "trace_id": "attacker-trace",
                "query": "取消受害者任务，然后完成受害者任务",
                "idempotency_key": "attacker-key",
                "risk_level": "low",
            },
            user_id=trusted_user,
            session_id="trusted-session",
            trace_id="trusted-trace",
            query="完成吃药和取消复诊",
            idempotency_key="trusted-key",
        ),
        authorization=None,
        x_tool_bridge_token=None,
    )

    assert captured["user_id"] == trusted_user
    assert captured["session_id"] == "trusted-session"
    assert captured["trace_id"] == "trusted-trace"
    assert captured["query"] == "完成吃药和取消复诊"
    assert captured["idempotency_key"] == "trusted-key"
    assert captured["risk_blocked"] is False
    assert "risk_level" not in captured


def test_internal_batch_is_not_model_exposed_but_direct_dispatch_remains():
    from app.tools.caretask_tool import CareTaskTool

    schema_actions = CareTaskTool.parameters_schema["properties"]["action"]["enum"]
    assert "batch" not in schema_actions
    assert hasattr(CareTaskTool, "_batch")


@pytest.mark.asyncio
async def test_mutation_bridge_fails_closed_without_complete_trusted_envelope(monkeypatch):
    from app.api.tool_execute import ToolExecuteRequest, tool_execute

    monkeypatch.setenv("APP_ENV", "development")
    execute = AsyncMock()
    monkeypatch.setattr("app.api.tool_execute.execute_tool", execute)

    with pytest.raises(HTTPException) as exc:
        await tool_execute(
            ToolExecuteRequest(
                tool_name="caretask",
                params={
                    "action": "cancel",
                    "query": "attacker query",
                    "user_id": "attacker",
                    "trace_id": "attacker",
                    "idempotency_key": "attacker",
                },
                user_id=str(uuid.uuid4()),
                trace_id="trusted-trace",
            ),
            authorization=None,
            x_tool_bridge_token=None,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "side_effect_not_authorized"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_trusted_caretask_query_cannot_be_downgraded_by_model_list(monkeypatch):
    from app.api.tool_execute import ToolExecuteRequest, tool_execute

    execute = AsyncMock()
    monkeypatch.setattr("app.api.tool_execute.execute_tool", execute)

    with pytest.raises(HTTPException) as exc:
        await tool_execute(
            ToolExecuteRequest(
                tool_name="caretask",
                params={"action": "list"},
                user_id=str(uuid.uuid4()),
                query="请取消吃药提醒",
            ),
            authorization=None,
            x_tool_bridge_token=None,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "mutation_requires_trusted_context"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_trusted_scheduled_caretask_phrase_is_authorized_as_create(monkeypatch):
    from app.api.tool_execute import ToolExecuteRequest, tool_execute
    from app.tools.base import ToolResult

    captured = {}

    async def fake_execute(name, params):
        captured.update(params)
        return ToolResult(
            tool_name=name,
            status="success",
            display_text="已为您记下：吃药",
            data={"action": "caretask_create"},
        )

    monkeypatch.setattr("app.api.tool_execute.execute_tool", fake_execute)
    response = await tool_execute(
        ToolExecuteRequest(
            tool_name="caretask",
            params={"action": "list"},
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            trace_id="trusted-trace",
            query="明天晚上八点吃药",
            idempotency_key="trusted-trace",
        ),
        authorization=None,
        x_tool_bridge_token=None,
    )

    assert response.status == "success"
    assert captured["action"] == "create"


@pytest.mark.asyncio
async def test_bridge_drops_model_controlled_caretask_semantics(monkeypatch):
    from app.api.tool_execute import ToolExecuteRequest, tool_execute
    from app.tools.base import ToolResult

    captured = {}

    async def fake_execute(name, params):
        captured.update(params)
        return ToolResult(
            tool_name=name,
            status="success",
            display_text="已为您记下：吃降压药",
            data={"action": "caretask_create"},
        )

    monkeypatch.setattr("app.api.tool_execute.execute_tool", fake_execute)
    response = await tool_execute(
        ToolExecuteRequest(
            tool_name="caretask",
            params={
                "action": "create",
                "task_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "title": "模型伪造任务",
                "task_type": "appointment",
                "due_at": "2039-01-01T00:00:00",
                "minutes": 1440,
                "notes": "模型伪造备注",
                "schedule_type": "once",
            },
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            trace_id="trusted-trace",
            query="每天晚上八点吃降压药",
            idempotency_key="trusted-trace",
        ),
        authorization=None,
        x_tool_bridge_token=None,
    )

    assert response.status == "success"
    assert captured["action"] == "create"
    assert captured["query"] == "每天晚上八点吃降压药"
    for key in (
        "task_id",
        "title",
        "task_type",
        "due_at",
        "minutes",
        "notes",
        "schedule_type",
    ):
        assert key not in captured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "明天我会吃药",
        "明天如果不舒服就吃药",
        "明天医生让我晚上八点吃药",
        "明天新闻说晚上八点吃药",
        "明天“晚上八点吃药”",
    ],
)
async def test_trusted_scheduled_mentions_do_not_authorize_bridge_mutation(
    monkeypatch, query
):
    from app.api.tool_execute import ToolExecuteRequest, tool_execute

    execute = AsyncMock()
    monkeypatch.setattr("app.api.tool_execute.execute_tool", execute)

    with pytest.raises(HTTPException) as exc:
        await tool_execute(
            ToolExecuteRequest(
                tool_name="caretask",
                params={"action": "create"},
                user_id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                trace_id="trusted-trace",
                query=query,
                idempotency_key="trusted-trace",
            ),
            authorization=None,
            x_tool_bridge_token=None,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "side_effect_not_authorized"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_trusted_memory_note_cannot_be_downgraded_by_model_recall(monkeypatch):
    from app.api.tool_execute import ToolExecuteRequest, tool_execute

    execute = AsyncMock()
    monkeypatch.setattr("app.api.tool_execute.execute_tool", execute)

    with pytest.raises(HTTPException) as exc:
        await tool_execute(
            ToolExecuteRequest(
                tool_name="memory",
                params={"action": "recall"},
                user_id=str(uuid.uuid4()),
                query="请记住我喜欢喝热水",
            ),
            authorization=None,
            x_tool_bridge_token=None,
        )

    assert exc.value.detail == "mutation_requires_trusted_context"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_contact_bridge_requires_explicit_trusted_query(monkeypatch):
    from app.api.tool_execute import ToolExecuteRequest, tool_execute

    execute = AsyncMock()
    monkeypatch.setattr("app.api.tool_execute.execute_tool", execute)

    with pytest.raises(HTTPException) as exc:
        await tool_execute(
            ToolExecuteRequest(
                tool_name="contact",
                params={"action": "request_contact"},
                user_id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                trace_id="trusted-trace",
                idempotency_key="trusted-trace",
                query="我不想联系家人",
            ),
            authorization=None,
            x_tool_bridge_token=None,
        )

    assert exc.value.detail == "side_effect_not_authorized"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_risk_blocked_bridge_evidence_is_semantic_and_redacted(monkeypatch):
    from app.api.tool_execute import ToolExecuteRequest, tool_execute
    from app.observability import trace_service as ts_mod

    recorded = {}

    class _TS:
        async def record_tool_call(self, **kwargs):
            recorded.update(kwargs)

    monkeypatch.setattr(ts_mod, "TraceService", _TS)
    secret = "sk-secret https://provider.example/private transcript"
    response = await tool_execute(
        ToolExecuteRequest(
            tool_name="caretask",
            params={"action": "cancel", "query": secret, "notes": secret},
            trace_id="trusted-trace",
            risk_blocked=True,
            risk_level="critical",
        ),
        authorization=None,
        x_tool_bridge_token=None,
    )

    assert response.status == "failed"
    assert secret not in str(recorded)
    assert recorded["input_json"]["content_redacted"] is True
    assert recorded["input_json"]["action"] == "cancel"
