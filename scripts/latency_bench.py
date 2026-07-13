#!/usr/bin/env python3
"""Deterministic latency benchmark for AgentHarness (CI-safe, mocked models).

Usage:
  python scripts/latency_bench.py
  python scripts/latency_bench.py --iterations 100 --json
  python scripts/latency_bench.py --baseline docs/evidence/latency-baseline.json
  python scripts/latency_bench.py --update-baseline docs/evidence/latency-baseline.json

No real API keys or Docker required — all model adapters are mocked in-process.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# Repo root on sys.path so `app.*` imports work when invoked from repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_API_ROOT = _REPO_ROOT / "apps" / "api"
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from app.engines.base import (  # noqa: E402
    EmotionResult,
    IntentResult,
    MemorySnapshot,
    PersonalityConfig,
    RiskResult,
)
from app.runtime.agent_harness import AgentHarness  # noqa: E402

DEFAULT_ITERATIONS = 100
DEFAULT_REGRESSION_PCT = 20.0
# Synthetic wall-clock samples on shared hosted runners can cross a percentage
# boundary by a fraction of a millisecond due to scheduler jitter. This is only
# added to the baseline-relative limit; absolute ceilings remain unchanged.
HOSTED_RUNNER_JITTER_MS = 0.5

# Absolute ceilings (ms) — hard fail even without baseline drift.
ABSOLUTE_THRESHOLDS: dict[str, float] = {
    "analyzer_ms_p95": 250.0,
    "ttft_ms_p95": 800.0,
    "total_ms_p95": 3000.0,
}


@dataclass(frozen=True)
class BenchFixture:
    name: str
    message: str
    intent: IntentResult
    emotion: EmotionResult
    risk: RiskResult
    memory: MemorySnapshot
    model_token_delay_ms: float = 2.0
    fast_reply: bool = False


FIXTURES: tuple[BenchFixture, ...] = (
    BenchFixture(
        name="chitchat",
        message="今天天气不错",
        intent=IntentResult(primary_intent="chitchat", confidence=0.9),
        emotion=EmotionResult(emotion="neutral", intensity=0.3),
        risk=RiskResult(level="low", category="none"),
        memory=MemorySnapshot(working=[{"role": "user", "content": "你好"}]),
        model_token_delay_ms=2.0,
    ),
    BenchFixture(
        name="scam_risk",
        message="我是公安局的，把你的验证码发给我",
        intent=IntentResult(primary_intent="chitchat", confidence=0.8),
        emotion=EmotionResult(emotion="anxious", intensity=0.6),
        risk=RiskResult(
            level="high",
            category="scam_alert",
            triggered_rules=["keyword:验证码"],
        ),
        memory=MemorySnapshot(),
        model_token_delay_ms=0.0,
    ),
    BenchFixture(
        name="reminder",
        message="每天晚上8点提醒我吃降压药",
        intent=IntentResult(
            primary_intent="reminder",
            confidence=0.95,
            tool_needs=["reminder"],
        ),
        emotion=EmotionResult(emotion="neutral", intensity=0.4),
        risk=RiskResult(level="low", category="none"),
        memory=MemorySnapshot(profile={"medication": "降压药"}),
        model_token_delay_ms=3.0,
    ),
)


@dataclass
class RunSample:
    fixture: str
    iteration: int
    analyzer_ms: float
    ttft_ms: float | None
    total_ms: float
    blocked_by_risk: bool


@dataclass
class FixtureStats:
    fixture: str
    samples: int
    analyzer_ms: dict[str, float]
    ttft_ms: dict[str, float]
    total_ms: dict[str, float]
    blocked_by_risk_count: int = 0


@dataclass
class BenchReport:
    iterations_per_fixture: int
    fixtures: list[FixtureStats] = field(default_factory=list)
    passed: bool = True
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "iterations_per_fixture": self.iterations_per_fixture,
            "passed": self.passed,
            "failures": self.failures,
            "fixtures": [asdict(f) for f in self.fixtures],
        }


def percentile(values: list[float], pct: float) -> float:
    """Return the pct-th percentile (0–100) using nearest-rank."""
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return float(ordered[rank])


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": max(values),
    }


class _MockModel:
    def __init__(self, token_delay_ms: float, tokens: tuple[str, ...] = ("你", "好", "。")):
        self.provider = "mock"
        self.model_name = "latency-mock"
        self._token_delay_ms = token_delay_ms
        self._tokens = tokens

    async def stream_chat(self, messages: list[dict[str, str]]):
        for token in self._tokens:
            if self._token_delay_ms > 0:
                await asyncio.sleep(self._token_delay_ms / 1000.0)
            yield token

    def count_tokens(self, text: str) -> int:
        return max(1, len(text or ""))


def _install_harness_mocks(
    harness: AgentHarness,
    fixture: BenchFixture,
    monkeypatch: Any,
    timing: dict[str, float],
) -> None:
    """Patch harness dependencies for deterministic latency measurement."""

    async def fake_analyzers(_input):
        t0 = time.monotonic()
        await asyncio.sleep(0.005)
        timing["analyzer_ms"] = (time.monotonic() - t0) * 1000.0
        return fixture.intent, fixture.emotion, fixture.risk, fixture.memory

    async def fake_personality(*_args, **_kwargs):
        return PersonalityConfig(tone="warm", max_length=80)

    async def fake_fast_reply(*_args, **_kwargs):
        return fixture.fast_reply

    async def fake_persist(*_args, **_kwargs):
        return None

    async def fake_dispatch_tools(*_args, **_kwargs):
        await asyncio.sleep(0.002)
        return [{"tool_name": "reminder", "status": "ok"}]

    async def fake_risk_notification(*_args, **_kwargs):
        return {"status": "skipped", "records": 0}

    async def fake_persist_turn_messages(**kwargs):
        return SimpleNamespace(
            assistant_message_id=kwargs["assistant_message_id"],
        )

    harness._run_analyzers = fake_analyzers  # type: ignore[method-assign]
    harness._get_personality = fake_personality  # type: ignore[method-assign]
    harness._fast_reply_race = fake_fast_reply  # type: ignore[method-assign]
    harness._persist_conversation = fake_persist  # type: ignore[method-assign]
    harness._dispatch_tools = fake_dispatch_tools  # type: ignore[method-assign]
    harness._dispatch_risk_notification = fake_risk_notification  # type: ignore[method-assign]

    class _Router:
        async def get_model(self, role: str):
            delay = fixture.model_token_delay_ms if role != "fast" else 1.0
            return _MockModel(delay)

    import app.models.router as router_mod
    import app.observability.message_evidence as message_evidence_mod
    import app.runtime.agent_harness as harness_mod

    monkeypatch.setattr(router_mod, "model_router", _Router())
    monkeypatch.setattr(
        message_evidence_mod,
        "persist_turn_messages",
        fake_persist_turn_messages,
    )
    monkeypatch.setattr(harness_mod._trace_svc, "add_event", _async_noop)
    monkeypatch.setattr(harness_mod._trace_svc, "record_model_call", _async_noop)


async def _async_noop(**_kwargs):
    return None


class _RecordingStreamManager:
    """Minimal stream manager that records timing without a WebSocket."""

    dead = False

    def __init__(self) -> None:
        self.trace_sent_at: float | None = None
        self.first_reply_at: float | None = None
        self.final_at: float | None = None
        self.ttft_ms: int | None = None

    async def send_trace(self, trace_id: str) -> None:
        self.trace_sent_at = time.monotonic()

    async def send_risk_alert(self, level: str, message: str) -> None:
        return None

    async def send_first_reply(self, text: str, ttft_ms: int) -> None:
        self.first_reply_at = time.monotonic()
        self.ttft_ms = ttft_ms

    async def send_delta(self, text: str) -> None:
        return None

    async def send_final(self, **kwargs) -> None:
        self.final_at = time.monotonic()

    async def send_error(self, code: str, message: str, retry: bool = False) -> None:
        return None


class _MonkeyPatch:
    """Tiny stand-in for pytest monkeypatch when running as a script."""

    def __init__(self) -> None:
        self._originals: list[tuple[Any, str, Any]] = []

    def setattr(self, obj: Any, name: str, value: Any) -> None:
        self._originals.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def restore(self) -> None:
        for obj, name, orig in reversed(self._originals):
            setattr(obj, name, orig)


async def run_single(
    harness: AgentHarness,
    fixture: BenchFixture,
    iteration: int,
    monkeypatch: _MonkeyPatch,
) -> RunSample:
    timing: dict[str, float] = {}
    _install_harness_mocks(harness, fixture, monkeypatch, timing)
    stream = _RecordingStreamManager()
    cancel = asyncio.Event()
    t0 = time.monotonic()
    result = await harness.run(
        user_id="bench-user-001",
        session_id="bench-session-001",
        message=fixture.message,
        stream_mgr=stream,  # type: ignore[arg-type]
        cancel_event=cancel,
    )
    total_ms = (time.monotonic() - t0) * 1000.0
    analyzer_ms = timing.get("analyzer_ms", 0.0)
    ttft = result.get("ttft_ms")
    if ttft is None and stream.ttft_ms is not None:
        ttft = stream.ttft_ms
    return RunSample(
        fixture=fixture.name,
        iteration=iteration,
        analyzer_ms=analyzer_ms,
        ttft_ms=float(ttft) if ttft is not None else None,
        total_ms=total_ms,
        blocked_by_risk=bool(result.get("blocked_by_risk")),
    )


async def run_benchmark(iterations: int = DEFAULT_ITERATIONS) -> BenchReport:
    report = BenchReport(iterations_per_fixture=iterations)
    harness = AgentHarness()

    for fixture in FIXTURES:
        samples: list[RunSample] = []
        for i in range(iterations):
            mp = _MonkeyPatch()
            try:
                sample = await run_single(harness, fixture, i, mp)
            finally:
                mp.restore()
            samples.append(sample)

        analyzer_vals = [s.analyzer_ms for s in samples]
        ttft_vals = [s.ttft_ms for s in samples if s.ttft_ms is not None]
        total_vals = [s.total_ms for s in samples]

        report.fixtures.append(
            FixtureStats(
                fixture=fixture.name,
                samples=len(samples),
                analyzer_ms=summarize(analyzer_vals),
                ttft_ms=summarize(ttft_vals),
                total_ms=summarize(total_vals),
                blocked_by_risk_count=sum(1 for s in samples if s.blocked_by_risk),
            )
        )

    return report


def check_absolute_thresholds(report: BenchReport) -> list[str]:
    failures: list[str] = []
    for fx in report.fixtures:
        checks = (
            ("analyzer_ms_p95", fx.analyzer_ms.get("p95", 0.0)),
            ("ttft_ms_p95", fx.ttft_ms.get("p95", 0.0)),
            ("total_ms_p95", fx.total_ms.get("p95", 0.0)),
        )
        for key, value in checks:
            limit = ABSOLUTE_THRESHOLDS.get(key)
            if limit is not None and value > limit:
                failures.append(
                    f"{fx.fixture}: {key}={value:.1f}ms exceeds absolute limit {limit:.1f}ms"
                )
    return failures


def load_baseline(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def compare_to_baseline(
    report: BenchReport,
    baseline: dict[str, Any],
    max_regression_pct: float = DEFAULT_REGRESSION_PCT,
) -> list[str]:
    failures: list[str] = []
    baseline_fixtures = {f["fixture"]: f for f in baseline.get("fixtures", [])}

    metric_keys = (
        ("analyzer_ms", "p95"),
        ("ttft_ms", "p95"),
        ("total_ms", "p95"),
    )

    for fx in report.fixtures:
        base = baseline_fixtures.get(fx.fixture)
        if not base:
            failures.append(f"{fx.fixture}: missing from baseline — run --update-baseline")
            continue
        for section, stat in metric_keys:
            current = fx.__dict__[section].get(stat, 0.0)
            expected = base.get(section, {}).get(stat, 0.0)
            if expected <= 0:
                continue
            allowed = (
                expected * (1.0 + max_regression_pct / 100.0)
                + HOSTED_RUNNER_JITTER_MS
            )
            if current > allowed:
                failures.append(
                    f"{fx.fixture}: {section}_{stat} regressed "
                    f"{current:.1f}ms > {allowed:.1f}ms "
                    f"(baseline {expected:.1f}ms + {max_regression_pct:.0f}% "
                    f"+ {HOSTED_RUNNER_JITTER_MS:.1f}ms runner tolerance)"
                )
    return failures


def evaluate_report(
    report: BenchReport,
    baseline_path: Path | None = None,
    max_regression_pct: float = DEFAULT_REGRESSION_PCT,
) -> BenchReport:
    failures = check_absolute_thresholds(report)
    if baseline_path and baseline_path.is_file():
        baseline = load_baseline(baseline_path)
        failures.extend(compare_to_baseline(report, baseline, max_regression_pct))
    report.failures = failures
    report.passed = not failures
    return report


def baseline_from_report(report: BenchReport) -> dict[str, Any]:
    return {
        "version": 1,
        "iterations_per_fixture": report.iterations_per_fixture,
        "fixtures": [
            {
                "fixture": fx.fixture,
                "analyzer_ms": fx.analyzer_ms,
                "ttft_ms": fx.ttft_ms,
                "total_ms": fx.total_ms,
            }
            for fx in report.fixtures
        ],
    }


def format_report(report: BenchReport) -> str:
    lines = [
        f"latency_bench passed={report.passed} iterations={report.iterations_per_fixture}",
    ]
    for fx in report.fixtures:
        lines.append(
            f"  [{fx.fixture}] analyzer_p95={fx.analyzer_ms['p95']:.1f}ms "
            f"ttft_p95={fx.ttft_ms['p95']:.1f}ms "
            f"total_p95={fx.total_ms['p95']:.1f}ms "
            f"risk_blocks={fx.blocked_by_risk_count}"
        )
    for msg in report.failures:
        lines.append(f"  FAIL: {msg}")
    return "\n".join(lines)


async def async_main(args: argparse.Namespace) -> int:
    report = await run_benchmark(iterations=args.iterations)
    baseline_path = Path(args.baseline) if args.baseline else None

    if args.update_baseline:
        out = Path(args.update_baseline)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = baseline_from_report(report)
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote baseline to {out}", file=sys.stderr)

    report = evaluate_report(
        report,
        baseline_path=baseline_path or (_REPO_ROOT / "docs/evidence/latency-baseline.json"),
        max_regression_pct=args.regression_pct,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report))

    return 0 if report.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentHarness latency benchmark (mocked, CI-safe)")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--baseline", type=str, default="", help="Baseline JSON for regression compare")
    parser.add_argument("--update-baseline", type=str, default="", help="Write baseline JSON from this run")
    parser.add_argument("--regression-pct", type=float, default=DEFAULT_REGRESSION_PCT)
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args(argv)
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
