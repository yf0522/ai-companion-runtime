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
from app.runtime.pi_runtime import (
    PiExperimentalRuntime,
    _authoritative_tool_text,
    _bounded_tool_receipt_copy,
    _semantic_audit_outcome,
)
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


@pytest.mark.parametrize("semantic_status", ["refused", "pending", "unauthorized", "failed", "timeout"])
def test_memory_terminal_semantic_status_is_authoritative(semantic_status):
    assert _authoritative_tool_text({
        "type": "tool_result",
        "tool": "memory",
        "status": "success",
        "text": "这项长期偏好还没有保存。",
        "data": {"status": semantic_status},
    }) == "这项长期偏好还没有保存。"


@pytest.mark.parametrize("status", ["success", "failed", "timeout", "needs_clarification"])
def test_every_caretask_terminal_result_is_authoritative(status):
    assert _authoritative_tool_text({
        "type": "tool_result", "tool": "caretask", "status": status, "text": "照护事项结果"
    }) == "照护事项结果"


@pytest.mark.parametrize("delivery_status", ["no_verified_contact", "recorded", "queued", "pending", "delivered"])
def test_every_contact_delivery_outcome_is_authoritative(delivery_status):
    assert _authoritative_tool_text({
        "type": "tool_result",
        "tool": "contact",
        "status": "success",
        "text": "联系家人结果",
        "data": {"delivery_status": delivery_status},
    }) == "联系家人结果"


def test_tool_receipt_audit_copy_is_deterministic_bounded_and_redacted():
    copied = _bounded_tool_receipt_copy({
        "action": "caretask_batch",
        "query": "raw private message",
        "receipts": [
            {"index": i, "action": "create", "status": "completed", "raw_text": "secret"}
            for i in range(25)
        ],
    })
    assert copied["action"] == "caretask_batch"
    assert len(copied["receipts"]) == 20
    assert copied["receipts_truncated"] is True
    assert "query" not in copied
    assert "raw_text" not in str(copied)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (
            {"action": "contact_help_request", "delivery_status": "queued", "raw_text": "secret"},
            {"action": "contact_help_request", "delivery_status": "queued"},
        ),
        (
            {"action": "caretask_complete", "status": "success", "task_id": "task-42", "query": "private"},
            {"action": "caretask_complete", "status": "success", "task_id": "task-42"},
        ),
        (
            {"action": "memory_note", "status": "refused", "text": "private"},
            {"action": "memory_note", "status": "refused"},
        ),
        (
            {"action": "memory_note", "status": "pending", "task_id": "task-1", "reason": "consent_required"},
            {"action": "memory_note", "status": "pending", "task_id": "task-1", "reason": "consent_required"},
        ),
    ],
)
def test_tool_receipt_copy_preserves_authoritative_semantic_status(data, expected):
    assert _bounded_tool_receipt_copy(data) == expected


@pytest.mark.parametrize(
    ("tool", "transport", "data", "expected"),
    [
        ("memory", "success", {"status": "refused"}, ("memory_refused", "refused")),
        (
            "contact", "success",
            {"status": "persisted", "delivery_status": "queued"},
            ("contact_queued", "queued"),
        ),
        (
            "contact", "success",
            {"status": "persisted", "delivery_status": "no_verified_contact"},
            ("contact_no_verified_contact", "no_verified_contact"),
        ),
        ("caretask", "failed", {}, ("caretask_failed", "failed")),
        (None, None, None, ("assistant_completed", None)),
    ],
)
def test_semantic_audit_outcome_uses_authoritative_domain_state(
    tool, transport, data, expected
):
    assert _semantic_audit_outcome(tool, transport, data) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "status", "data", "truth"),
    [
        ("memory", "success", {"status": "refused"}, "这项长期偏好不能保存。"),
        ("contact", "success", {"delivery_status": "queued"}, "联系请求已排队，送达待确认。"),
        ("caretask", "failed", {"action": "caretask_batch"}, "1. 吃药：失败\n2. 复诊：未执行"),
    ],
)
async def test_terminal_tool_truth_suppresses_later_model_delta(
    monkeypatch, tool, status, data, truth
):
    class FakeResponse:
        status_code = 200

        async def aiter_lines(self):
            yield json.dumps({"type": "text_delta", "delta": "模型先说成功。"})
            yield json.dumps({
                "type": "tool_result", "tool": tool, "status": status,
                "text": truth, "data": data,
            })
            yield json.dumps({"type": "text_delta", "delta": "已经全部完成并送达。"})
            yield json.dumps({"type": "done"})

        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return False

    class FakeClient:
        def stream(self, *_args, **_kwargs): return FakeResponse()
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return False

    monkeypatch.setattr("app.runtime.pi_runtime.httpx.AsyncClient", lambda **_kwargs: FakeClient())
    monkeypatch.setattr("app.runtime.pi_runtime._persist_turn_best_effort", AsyncMock(return_value=None))
    stream = MagicMock(dead=False)
    stream.send_tool_result = AsyncMock()
    stream.send_tool_status = AsyncMock()
    stream.send_first_reply = AsyncMock()
    stream.send_final = AsyncMock()
    result = await PiExperimentalRuntime()._run_sidecar(
        user_id="user-1", session_id="session-1", message="测试",
        stream_mgr=stream, cancel_event=asyncio.Event(), trace_id="trace-terminal",
        start=0.0,
    )
    assert result["response_text"] == truth
    assert "已经全部完成" not in result["response_text"]
    stream.send_first_reply.assert_awaited_once_with(truth, ANY)


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
            metadata={
                "trace_id": "trace_test_pi",
                "decision_persistence": {
                    "status": "failed", "error_class": "RuntimeError",
                    "error_code": "decision_persistence_failed", "outbox_ids": [],
                },
            },
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
    assert result["decision_persistence"]["error_code"] == "decision_persistence_failed"
    stream.send_first_reply.assert_awaited()


@pytest.mark.asyncio
async def test_pi_enabled_sidecar_failure_reports_runtime_unavailable(monkeypatch, caplog):
    async def fake_gate(**_kwargs):
        from app.engines.base import RiskResult
        from app.runtime.risk_gate import RiskGateOutcome

        return RiskGateOutcome(
            blocked=False,
            risk=RiskResult(level="low"),
            trace_id="trace-sidecar-unavailable",
            metadata={"trace_id": "trace-sidecar-unavailable"},
        )

    async def fail_sidecar(*_args, **_kwargs):
        raise RuntimeError("provider secret must not affect user-facing truth")

    monkeypatch.setattr("app.runtime.pi_runtime.run_risk_gate", fake_gate)
    monkeypatch.setattr("app.runtime.pi_runtime.settings.enable_pi_runtime", True)
    monkeypatch.setattr("app.runtime.pi_runtime.PiExperimentalRuntime._run_sidecar", fail_sidecar)
    stream = MagicMock(dead=False)
    stream.send_first_reply = AsyncMock()
    stream.send_final = AsyncMock()

    result = await PiExperimentalRuntime().run(
        user_id="user-1",
        session_id="session-1",
        message="你好",
        stream_mgr=stream,
        cancel_event=asyncio.Event(),
    )

    assert result["error"] == "pi_runtime_unavailable"
    reply = stream.send_first_reply.await_args.args[0]
    assert "尚未在本环境启用" not in reply
    assert "暂时不可用" in reply
    assert "provider secret" not in reply
    assert "provider secret" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert "trace=trace-sidecar-unavailable" in caplog.text
    assert "code=pi_runtime_unavailable" in caplog.text
    stream.send_final.assert_awaited_once()


@pytest.mark.asyncio
async def test_pi_disabled_final_emits_despite_hanging_audit(monkeypatch):
    async def fake_gate(**_kwargs):
        from app.engines.base import RiskResult
        from app.runtime.risk_gate import RiskGateOutcome

        return RiskGateOutcome(
            blocked=False, risk=RiskResult(level="low"), trace_id="trace-hang",
            metadata={"trace_id": "trace-hang"},
        )

    async def hang(**_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr("app.runtime.pi_runtime.run_risk_gate", fake_gate)
    monkeypatch.setattr("app.runtime.pi_runtime.settings.enable_pi_runtime", False)
    monkeypatch.setattr("app.runtime.pi_runtime._persist_turn_best_effort", hang)
    monkeypatch.setattr("app.runtime.pi_runtime._AUDIT_TIMEOUT_S", 0.001)
    stream = MagicMock(dead=False)
    stream.send_first_reply = AsyncMock()
    stream.send_final = AsyncMock()

    result = await PiExperimentalRuntime().run(
        user_id="user-1", session_id="session-1", message="你好",
        stream_mgr=stream, cancel_event=asyncio.Event(),
    )

    assert result["error"] == "pi_experimental_not_enabled"
    stream.send_first_reply.assert_awaited_once()
    stream.send_final.assert_awaited_once()


@pytest.mark.asyncio
async def test_pi_disabled_final_emits_despite_raising_audit(monkeypatch):
    async def fake_gate(**_kwargs):
        from app.engines.base import RiskResult
        from app.runtime.risk_gate import RiskGateOutcome

        return RiskGateOutcome(
            blocked=False, risk=RiskResult(level="low"), trace_id="trace-raise",
            metadata={"trace_id": "trace-raise"},
        )

    async def fail(**_kwargs):
        raise RuntimeError("postgres unavailable")

    monkeypatch.setattr("app.runtime.pi_runtime.run_risk_gate", fake_gate)
    monkeypatch.setattr("app.runtime.pi_runtime.settings.enable_pi_runtime", False)
    monkeypatch.setattr("app.runtime.pi_runtime._persist_turn_best_effort", fail)
    stream = MagicMock(dead=False)
    stream.send_first_reply = AsyncMock()
    stream.send_final = AsyncMock()

    result = await PiExperimentalRuntime().run(
        user_id="user-1", session_id="session-1", message="你好",
        stream_mgr=stream, cancel_event=asyncio.Event(),
    )

    assert result["error"] == "pi_experimental_not_enabled"
    stream.send_final.assert_awaited_once()


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
async def test_pi_audit_uses_final_terminal_tool_for_repeated_tool_stream(monkeypatch):
    events = [
        {"type": "tool_result", "tool": "contact", "status": "success", "text": "已记录", "data": {"delivery_status": "queued"}},
        {"type": "tool_result", "tool": "memory", "status": "success", "text": "尚未保存", "data": {"status": "pending"}},
        {"type": "tool_result", "tool": "contact", "status": "failed", "text": "联系失败", "data": {"delivery_status": "failed"}},
        {"type": "done"},
    ]

    class FakeResponse:
        status_code = 200
        async def aiter_lines(self):
            for event in events:
                yield json.dumps(event)
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return False

    class FakeClient:
        def stream(self, *_args, **_kwargs): return FakeResponse()
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return False

    audit = AsyncMock()
    monkeypatch.setattr("app.runtime.pi_runtime.httpx.AsyncClient", lambda **_kwargs: FakeClient())
    monkeypatch.setattr("app.runtime.pi_runtime._persist_pi_evidence_best_effort", audit)
    stream = MagicMock(dead=False)
    stream.send_tool_result = AsyncMock()
    stream.send_tool_status = AsyncMock()
    stream.send_first_reply = AsyncMock()
    stream.send_final = AsyncMock()

    await PiExperimentalRuntime()._run_sidecar(
        user_id="user-1", session_id="session-1", message="help", stream_mgr=stream,
        cancel_event=asyncio.Event(), trace_id="trace-aba", start=0.0,
    )

    assert audit.await_args.kwargs["tool_name"] == "contact"
    assert audit.await_args.kwargs["tool_status"] == "failed"
    assert audit.await_args.kwargs["tool_data"] == {"delivery_status": "failed"}


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
