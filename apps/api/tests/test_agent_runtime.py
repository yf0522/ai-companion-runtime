"""Agent runtime selector tests — default harness, Pi stub, unknown rejection."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

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
