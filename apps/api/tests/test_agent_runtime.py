"""Agent runtime selector tests — default harness, Pi stub, unknown rejection."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from app.runtime.agent_runtime import (
    DEFAULT_RUNTIME,
    RUNTIME_HARNESS,
    RUNTIME_PI_EXPERIMENTAL,
    get_agent_runtime,
    normalize_runtime_name,
)
from app.runtime.harness_runtime import HarnessRuntime
from app.runtime.pi_runtime import PiExperimentalRuntime
from app.tools.base import ToolResult


def test_normalize_runtime_defaults_to_harness():
    assert normalize_runtime_name(None) == DEFAULT_RUNTIME
    assert normalize_runtime_name("") == DEFAULT_RUNTIME
    assert normalize_runtime_name("harness") == RUNTIME_HARNESS
    assert normalize_runtime_name("pi") == RUNTIME_PI_EXPERIMENTAL
    assert normalize_runtime_name("PI_EXPERIMENTAL") == RUNTIME_PI_EXPERIMENTAL


def test_normalize_runtime_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown agent runtime"):
        normalize_runtime_name("openai_agents")


def test_get_agent_runtime_factory():
    assert isinstance(get_agent_runtime("harness"), HarnessRuntime)
    assert isinstance(get_agent_runtime("pi_experimental"), PiExperimentalRuntime)
    assert get_agent_runtime(None).name == RUNTIME_HARNESS


@pytest.mark.asyncio
async def test_pi_runtime_runs_risk_gate_before_stub(monkeypatch):
    gate_called = {"ok": False}

    async def fake_gate(**kwargs):
        gate_called["ok"] = True
        from app.runtime.risk_gate import RiskGateOutcome
        from app.engines.base import RiskResult

        return RiskGateOutcome(
            blocked=False,
            risk=RiskResult(level="low"),
            trace_id="trace_test_pi",
            metadata={"trace_id": "trace_test_pi"},
        )

    monkeypatch.setattr("app.runtime.pi_runtime.run_risk_gate", fake_gate)
    monkeypatch.setattr("app.runtime.pi_runtime.settings.enable_pi_runtime", False)

    runtime = PiExperimentalRuntime()
    stream = MagicMock()
    stream.send_trace = AsyncMock()
    stream.send_first_reply = AsyncMock()
    stream.send_final = AsyncMock()

    result = await runtime.run(
        user_id="user-1",
        session_id="session-1",
        message="你好",
        stream_mgr=stream,
        cancel_event=asyncio.Event(),
    )

    assert gate_called["ok"] is True
    assert result["agent_runtime"] == RUNTIME_PI_EXPERIMENTAL
    assert result.get("error") == "pi_experimental_not_enabled"
    stream.send_first_reply.assert_awaited()


@pytest.mark.asyncio
async def test_pi_runtime_compound_caretask_bypasses_sidecar(monkeypatch):
    async def fake_gate(**kwargs):
        from app.runtime.risk_gate import RiskGateOutcome
        from app.engines.base import RiskResult

        return RiskGateOutcome(
            blocked=False,
            risk=RiskResult(level="low"),
            trace_id="trace_batch",
            metadata={"trace_id": "trace_batch"},
        )

    execute = AsyncMock(return_value=ToolResult(
        tool_name="caretask",
        status="success",
        display_text="1. 查看：已完成\n2. 推迟：已完成",
        data={"action": "caretask_batch", "receipts": []},
    ))
    sidecar = AsyncMock()
    monkeypatch.setattr("app.runtime.pi_runtime.run_risk_gate", fake_gate)
    monkeypatch.setattr("app.runtime.pi_runtime.PiExperimentalRuntime._run_sidecar", sidecar)
    monkeypatch.setattr("app.tools.caretask_tool.CareTaskTool.execute", execute)

    stream = MagicMock(dead=False)
    stream.send_tool_status = AsyncMock()
    stream.send_tool_result = AsyncMock()
    stream.send_first_reply = AsyncMock()
    stream.send_final = AsyncMock()
    result = await PiExperimentalRuntime().run(
        user_id="user-1",
        session_id="session-1",
        message="看看今天的任务，然后把降压药推迟30分钟",
        stream_mgr=stream,
        cancel_event=asyncio.Event(),
    )

    sidecar.assert_not_awaited()
    stream.send_tool_status.assert_awaited_once_with("caretask", "calling")
    stream.send_tool_result.assert_awaited_once()
    stream.send_first_reply.assert_awaited_once()
    stream.send_final.assert_awaited_once()
    assert result["tools_used"] == [{"tool": "caretask", "action": "caretask_batch", "status": "success"}]


@pytest.mark.asyncio
async def test_pi_runtime_streams_from_sidecar_when_enabled(monkeypatch):
    async def fake_gate(**kwargs):
        from app.runtime.risk_gate import RiskGateOutcome
        from app.engines.base import RiskResult

        return RiskGateOutcome(
            blocked=False,
            risk=RiskResult(level="low"),
            trace_id="trace_pi_sidecar",
            metadata={"trace_id": "trace_pi_sidecar"},
        )

    class FakeResponse:
        status_code = 200

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield json.dumps({"type": "text_delta", "delta": "你好"})
            yield json.dumps({"type": "done", "reason": "stop"})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class FakeClient:
        def stream(self, method, url, json=None):
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.runtime.pi_runtime.run_risk_gate", fake_gate)
    monkeypatch.setattr("app.runtime.pi_runtime.settings.enable_pi_runtime", True)
    monkeypatch.setattr("app.runtime.pi_runtime.settings.pi_sidecar_url", "http://127.0.0.1:8787")
    monkeypatch.setattr("app.runtime.pi_runtime.httpx.AsyncClient", lambda **kwargs: FakeClient())

    runtime = PiExperimentalRuntime()
    stream = MagicMock()
    stream.dead = False
    stream.send_trace = AsyncMock()
    stream.send_first_reply = AsyncMock()
    stream.send_delta = AsyncMock()
    stream.send_final = AsyncMock()

    result = await runtime.run(
        user_id="user-1",
        session_id="session-1",
        message="你好",
        stream_mgr=stream,
        cancel_event=asyncio.Event(),
    )

    assert result["agent_runtime"] == RUNTIME_PI_EXPERIMENTAL
    assert result.get("response_text") == "你好"
    assert "error" not in result
    stream.send_first_reply.assert_awaited_once()
    stream.send_delta.assert_not_awaited()
    stream.send_final.assert_awaited_once()


@pytest.mark.asyncio
async def test_pi_runtime_discards_model_preamble_after_successful_caretask(monkeypatch):
    async def fake_gate(**kwargs):
        from app.runtime.risk_gate import RiskGateOutcome
        from app.engines.base import RiskResult

        return RiskGateOutcome(
            blocked=False,
            risk=RiskResult(level="low"),
            trace_id="trace_pi_caretask",
            metadata={"trace_id": "trace_pi_caretask"},
        )

    class FakeResponse:
        status_code = 200

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield json.dumps({"type": "text_delta", "delta": "我来帮您记一下。"})
            yield json.dumps(
                {
                    "type": "tool_result",
                    "tool": "caretask",
                    "status": "success",
                    "text": "已为您记下：吃降糖药",
                    "action": "caretask_create",
                    "data": {"action": "caretask_create"},
                }
            )
            yield json.dumps({"type": "done", "reason": "tool_terminated"})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class FakeClient:
        def stream(self, method, url, json=None):
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.runtime.pi_runtime.run_risk_gate", fake_gate)
    monkeypatch.setattr("app.runtime.pi_runtime.settings.enable_pi_runtime", True)
    monkeypatch.setattr("app.runtime.pi_runtime.settings.pi_sidecar_url", "http://127.0.0.1:8787")
    monkeypatch.setattr("app.runtime.pi_runtime.httpx.AsyncClient", lambda **kwargs: FakeClient())

    runtime = PiExperimentalRuntime()
    stream = MagicMock()
    stream.dead = False
    stream.send_trace = AsyncMock()
    stream.send_first_reply = AsyncMock()
    stream.send_delta = AsyncMock()
    stream.send_tool_result = AsyncMock()
    stream.send_tool_status = AsyncMock()
    stream.send_final = AsyncMock()

    result = await runtime.run(
        user_id="user-1",
        session_id="session-1",
        message="提醒我吃降糖药",
        stream_mgr=stream,
        cancel_event=asyncio.Event(),
    )

    assert result["response_text"] == "已为您记下：吃降糖药"
    stream.send_first_reply.assert_awaited_once_with("已为您记下：吃降糖药", ANY)
    stream.send_delta.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("contact_status", "contact_text", "delivery_status"),
    [
        (
            "success",
            "求助请求已记录并进入联系队列，送达状态还在确认。",
            "queued",
        ),
        (
            "failed",
            "这次没有成功发出联系请求，请直接联系身边可信任的人。",
            "failed",
        ),
    ],
)
async def test_pi_runtime_uses_truthful_contact_result_as_authoritative_reply(
    monkeypatch,
    contact_status,
    contact_text,
    delivery_status,
):
    async def fake_gate(**kwargs):
        from app.runtime.risk_gate import RiskGateOutcome
        from app.engines.base import RiskResult

        return RiskGateOutcome(
            blocked=False,
            risk=RiskResult(level="low"),
            trace_id="trace_pi_contact",
            metadata={"trace_id": "trace_pi_contact"},
        )

    class FakeResponse:
        status_code = 200

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield json.dumps({"type": "text_delta", "delta": "好的，我已经通知家人了。"})
            yield json.dumps(
                {
                    "type": "tool_result",
                    "tool": "contact",
                    "status": contact_status,
                    "text": contact_text,
                    "action": "contact_help_request",
                    "data": {
                        "action": "contact_help_request",
                        "delivery_status": delivery_status,
                    },
                }
            )
            yield json.dumps({"type": "done", "reason": "tool_terminated"})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class FakeClient:
        def stream(self, method, url, json=None):
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.runtime.pi_runtime.run_risk_gate", fake_gate)
    monkeypatch.setattr("app.runtime.pi_runtime.settings.enable_pi_runtime", True)
    monkeypatch.setattr("app.runtime.pi_runtime.settings.pi_sidecar_url", "http://127.0.0.1:8787")
    monkeypatch.setattr("app.runtime.pi_runtime.httpx.AsyncClient", lambda **kwargs: FakeClient())

    runtime = PiExperimentalRuntime()
    stream = MagicMock()
    stream.dead = False
    stream.send_trace = AsyncMock()
    stream.send_first_reply = AsyncMock()
    stream.send_delta = AsyncMock()
    stream.send_tool_result = AsyncMock()
    stream.send_tool_status = AsyncMock()
    stream.send_final = AsyncMock()

    result = await runtime.run(
        user_id="user-1",
        session_id="session-1",
        message="我想让家人知道我需要帮助",
        stream_mgr=stream,
        cancel_event=asyncio.Event(),
    )

    expected = contact_text
    assert result["response_text"] == expected
    assert "已经通知" not in result["response_text"]
    stream.send_first_reply.assert_awaited_once_with(expected, ANY)
    stream.send_delta.assert_not_awaited()


@pytest.mark.asyncio
async def test_pi_runtime_blocks_on_high_risk(monkeypatch):
    async def fake_gate(**kwargs):
        from app.runtime.risk_gate import RiskGateOutcome
        from app.engines.base import RiskResult

        return RiskGateOutcome(
            blocked=True,
            risk=RiskResult(level="high", category="scam_alert"),
            trace_id="trace_blocked",
            metadata={"trace_id": "trace_blocked", "blocked_by_risk": True},
        )

    monkeypatch.setattr("app.runtime.pi_runtime.run_risk_gate", fake_gate)

    runtime = PiExperimentalRuntime()
    stream = MagicMock()
    result = await runtime.run(
        user_id="user-1",
        session_id="session-1",
        message="把验证码给我",
        stream_mgr=stream,
        cancel_event=asyncio.Event(),
    )

    assert result["blocked_by_risk"] is True
    assert result["agent_runtime"] == RUNTIME_PI_EXPERIMENTAL
