"""Tests: tool dispatch persists ToolCall rows into Trace (best-effort)."""
from __future__ import annotations

import asyncio
from datetime import datetime
import re
from types import SimpleNamespace
import uuid
import pytest

from app.tools.base import ToolBase, ToolResult
from app.tools.dispatcher import ToolDispatcher


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeStream:
    def __init__(self):
        self.events: list[tuple] = []

    async def send_tool_status(self, tool: str, status: str):
        self.events.append(("status", tool, status))

    async def send_tool_result(self, tool: str, text: str, **kwargs):
        self.events.append(("result", tool, text, kwargs))

    async def send_reminder_create(self, data: dict):
        self.events.append(("reminder_create", data))


class _OkTool(ToolBase):
    name = "calculator"
    description = "ok"

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text="1+1 = 2",
            data={"expression": "1+1", "result": 2},
        )


class _SlowTool(ToolBase):
    name = "slow"
    description = "timeout"

    async def execute(self, params: dict) -> ToolResult:
        await asyncio.sleep(2)
        return ToolResult(tool_name=self.name, status="success", display_text="late")


@pytest.mark.asyncio
async def test_successful_tool_writes_tool_call(monkeypatch):
    recorded: list[dict] = []

    async def fake_record(**kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(
        "app.observability.trace_service.TraceService.record_tool_call",
        fake_record,
        raising=False,
    )

    # Patch at instance method level via TraceService constructor path used by dispatcher
    from app.observability import trace_service as ts_mod

    class _TS:
        async def record_tool_call(self, **kwargs):
            recorded.append(kwargs)

    monkeypatch.setattr(ts_mod, "TraceService", _TS)

    dispatcher = ToolDispatcher()
    dispatcher._tools = {"calculator": _OkTool()}
    stream = _FakeStream()

    results = await dispatcher.dispatch(
        ["calculator"], "算一下 1+1", "trace_test_1", stream
    )

    assert len(results) == 1
    assert results[0].status == "success"
    assert len(recorded) == 1
    assert recorded[0]["trace_id"] == "trace_test_1"
    assert recorded[0]["tool_name"] == "calculator"
    assert recorded[0]["status"] == "success"
    evidence = str(recorded[0])
    assert "算一下 1+1" not in evidence
    assert "1+1 = 2" not in evidence
    assert recorded[0]["input_json"]["content_redacted"] is True
    assert recorded[0]["output_json"]["content_redacted"] is True


@pytest.mark.asyncio
async def test_tool_call_evidence_never_persists_secret_text_or_provider_exception(monkeypatch):
    secret = "sk-secret transcript 123456"
    recorded: list[dict] = []

    class _SecretTool(ToolBase):
        name = "secret"
        description = "secret"

        async def execute(self, _params):
            raise RuntimeError(secret)

    from app.observability import trace_service as ts_mod

    class _TS:
        async def record_tool_call(self, **kwargs):
            recorded.append(kwargs)

    monkeypatch.setattr(ts_mod, "TraceService", _TS)
    dispatcher = ToolDispatcher()
    dispatcher._tools = {"secret": _SecretTool()}

    await dispatcher.dispatch(["secret"], secret, "trace-secret", _FakeStream())

    assert secret not in str(recorded)
    assert recorded[0]["output_json"] == {
        "status": "failed",
        "error_code": "tool_execution_failed",
        "error_class": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_tool_timeout_writes_timeout_status(monkeypatch):
    recorded: list[dict] = []

    from app.observability import trace_service as ts_mod

    class _TS:
        async def record_tool_call(self, **kwargs):
            recorded.append(kwargs)

    monkeypatch.setattr(ts_mod, "TraceService", _TS)

    dispatcher = ToolDispatcher(tool_timeout_ms=50)
    dispatcher._tools = {"slow": _SlowTool()}
    stream = _FakeStream()

    results = await dispatcher.dispatch(["slow"], "wait", "trace_timeout", stream)

    assert len(results) == 1
    assert results[0].status == "timeout"
    assert len(recorded) == 1
    assert recorded[0]["status"] == "timeout"
    assert recorded[0]["tool_name"] == "slow"


@pytest.mark.asyncio
async def test_trace_persistence_failure_does_not_crash_dispatch(monkeypatch):
    from app.observability import trace_service as ts_mod

    class _BoomTS:
        async def record_tool_call(self, **kwargs):
            raise RuntimeError("db down")

    monkeypatch.setattr(ts_mod, "TraceService", _BoomTS)

    dispatcher = ToolDispatcher()
    dispatcher._tools = {"calculator": _OkTool()}
    stream = _FakeStream()

    results = await dispatcher.dispatch(
        ["calculator"], "1+1", "trace_db_fail", stream
    )

    assert len(results) == 1
    assert results[0].status == "success"
    assert any(
        e[0] == "result" and e[1] == "calculator" and e[2] == "1+1 = 2"
        for e in stream.events
    )


@pytest.mark.asyncio
async def test_trace_service_sanitizes_hostile_tool_evidence_at_persistence_boundary(monkeypatch):
    persisted = {}

    class _DB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def add(self, row):
            persisted["row"] = row

        async def commit(self):
            return None

    monkeypatch.setattr("app.db.session.async_session", lambda: _DB())
    from app.observability.trace_service import TraceService

    secret = "sk-hostile https://provider.example/path transcript private-note db-error"
    await TraceService().record_tool_call(
        trace_id="trace-hostile",
        tool_name="caretask",
        input_json={
            "params": {"action": "cancel", "query": secret, "notes": secret, "token": secret},
            "provider_messages": [{"content": secret}],
        },
        output_json={
            "status": "failed",
            "display_text": secret,
            "data": {"task_id": "task-42", "exception": secret, "url": secret},
        },
        status="failed",
    )

    row = persisted["row"]
    evidence = str({"input": row.input_json, "output": row.output_json})
    assert secret not in evidence
    assert row.input_json["content_redacted"] is True
    assert row.input_json["action"] == "cancel"
    assert row.output_json["status"] == "failed"
    assert row.output_json["task_id"].startswith("redacted:")


def test_semantic_tool_evidence_redacts_tokens_in_id_fields_and_is_idempotent():
    from app.observability.trace_service import sanitize_tool_evidence

    synthetic_tokens = [
        "AQ" + "x" * 40,
        "headerpayload12.secondpayload12.signature123",
        "sk-" + "synthetic" * 4,
        "arbitrary-task-id",
    ]
    for value in synthetic_tokens:
        first = sanitize_tool_evidence({"task_id": value, "status": "failed"})
        second = sanitize_tool_evidence(first)
        assert value not in str(first)
        assert value not in str(second)
        assert first["task_id"].startswith("redacted:")
        assert second["task_id"] == first["task_id"]

    safe_id = str(uuid.uuid4())
    evidence = sanitize_tool_evidence({"task_id": safe_id, "status": "success"})
    assert evidence["task_id"] == safe_id


def test_semantic_tool_evidence_redacts_aq_dot_token_in_non_id_field_twice():
    from app.observability.trace_service import sanitize_tool_evidence

    synthetic_token = "AQ." + "synthetic_Payload-123" * 2

    first = sanitize_tool_evidence({"operation": synthetic_token, "status": "failed"})
    second = sanitize_tool_evidence(first)

    assert synthetic_token not in str(first)
    assert synthetic_token not in str(second)
    assert re.fullmatch(r"redacted:[0-9a-f]{12}", first["operation"])
    assert second["operation"] == first["operation"]


@pytest.mark.parametrize(
    "embedded_secret",
    [
        "op:AQ" + "x" * 40,
        "op:AQ." + "synthetic_Payload-123" * 2,
        "op:headerpayload12.secondpayload12.signature123",
    ],
)
def test_semantic_tool_evidence_redacts_embedded_secret_substrings(embedded_secret):
    from app.observability.trace_service import sanitize_tool_evidence

    evidence = sanitize_tool_evidence({"operation": embedded_secret, "status": "failed"})

    assert embedded_secret not in str(evidence)
    assert re.fullmatch(r"redacted:[0-9a-f]{12}", evidence["operation"])


@pytest.mark.asyncio
async def test_trace_reconstructs_from_messages_and_tools_without_events(monkeypatch):
    now = datetime(2026, 7, 12, 12, 0)
    user_id, session_id = uuid.uuid4(), uuid.uuid4()
    message = SimpleNamespace(
        id=uuid.uuid4(), user_id=user_id, session_id=session_id, role="user",
        content="请联系家人", message_index=0, created_at=now,
    )
    tool = SimpleNamespace(
        id=uuid.uuid4(), tool_name="contact", status="success", latency_ms=5,
        input_json={"action": "request_contact"},
        output_json={"delivery_status": "queued"}, created_at=now,
    )

    class _DB:
        def __init__(self):
            self.results = iter([_Rows([]), _Rows([]), _Rows([tool]), _Rows([message])])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def execute(self, _query):
            return next(self.results)

    monkeypatch.setattr("app.db.session.async_session", lambda: _DB())
    from app.observability.trace_service import TraceService

    trace = await TraceService().get_trace("trace_rebuilt")
    assert trace is not None
    assert trace["events"] == []
    assert trace["messages"][0]["content"] == "请联系家人"
    assert trace["tool_calls"][0]["output"]["delivery_status"] == "queued"
    assert trace["session_id"] == str(session_id)
