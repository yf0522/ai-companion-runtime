"""Unit tests for scripts/latency_bench.py helpers (no live API keys)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_latency_bench():
    path = Path(__file__).resolve().parents[3] / "scripts" / "latency_bench.py"
    spec = importlib.util.spec_from_file_location("latency_bench", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["latency_bench"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_percentile_and_summarize():
    mod = _load_latency_bench()
    assert mod.percentile([10.0, 20.0, 30.0, 40.0], 50) == 30.0
    summary = mod.summarize([5.0, 10.0, 15.0, 20.0])
    assert summary["p50"] == 15.0
    assert summary["max"] == 20.0


def test_compare_to_baseline_flags_regression():
    mod = _load_latency_bench()
    report = mod.BenchReport(iterations_per_fixture=1)
    report.fixtures.append(
        mod.FixtureStats(
            fixture="chitchat",
            samples=1,
            analyzer_ms={"p50": 6.0, "p95": 13.0, "max": 13.0},
            ttft_ms={"p50": 20.0, "p95": 30.0, "max": 30.0},
            total_ms={"p50": 40.0, "p95": 50.0, "max": 50.0},
        )
    )
    baseline = {
        "fixtures": [
            {
                "fixture": "chitchat",
                "analyzer_ms": {"p95": 10.0},
                "ttft_ms": {"p95": 25.0},
                "total_ms": {"p95": 45.0},
            }
        ]
    }
    failures = mod.compare_to_baseline(report, baseline, max_regression_pct=20.0)
    assert any("analyzer_ms_p95" in f for f in failures)
    assert not any("ttft_ms_p95" in f for f in failures)


def test_compare_to_baseline_allows_sub_millisecond_runner_noise():
    mod = _load_latency_bench()
    report = mod.BenchReport(iterations_per_fixture=5)
    report.fixtures.append(
        mod.FixtureStats(
            fixture="scam_risk",
            samples=5,
            analyzer_ms={"p50": 5.6, "p95": 5.6, "max": 5.6},
            ttft_ms={"p50": 9.0, "p95": 9.0, "max": 9.0},
            total_ms={"p50": 10.0, "p95": 11.1, "max": 11.1},
        )
    )
    baseline = {
        "fixtures": [
            {
                "fixture": "scam_risk",
                "analyzer_ms": {"p95": 5.6},
                "ttft_ms": {"p95": 9.0},
                "total_ms": {"p95": 9.102916810661554},
            }
        ]
    }

    failures = mod.compare_to_baseline(report, baseline, max_regression_pct=20.0)

    assert not any("total_ms_p95" in failure for failure in failures)


def test_compare_to_baseline_still_flags_meaningful_regression():
    mod = _load_latency_bench()
    report = mod.BenchReport(iterations_per_fixture=5)
    report.fixtures.append(
        mod.FixtureStats(
            fixture="scam_risk",
            samples=5,
            analyzer_ms={"p50": 5.6, "p95": 5.6, "max": 5.6},
            ttft_ms={"p50": 9.0, "p95": 9.0, "max": 9.0},
            total_ms={"p50": 11.0, "p95": 12.0, "max": 12.0},
        )
    )
    baseline = {
        "fixtures": [
            {
                "fixture": "scam_risk",
                "analyzer_ms": {"p95": 5.6},
                "ttft_ms": {"p95": 9.0},
                "total_ms": {"p95": 9.102916810661554},
            }
        ]
    }

    failures = mod.compare_to_baseline(report, baseline, max_regression_pct=20.0)

    assert any("total_ms_p95" in failure for failure in failures)


def test_absolute_thresholds():
    mod = _load_latency_bench()
    report = mod.BenchReport(iterations_per_fixture=1)
    report.fixtures.append(
        mod.FixtureStats(
            fixture="chitchat",
            samples=1,
            analyzer_ms={"p50": 300.0, "p95": 300.0, "max": 300.0},
            ttft_ms={"p50": 10.0, "p95": 10.0, "max": 10.0},
            total_ms={"p50": 100.0, "p95": 100.0, "max": 100.0},
        )
    )
    failures = mod.check_absolute_thresholds(report)
    assert any("analyzer_ms_p95" in f for f in failures)


async def test_run_benchmark_mocked_passes():
    mod = _load_latency_bench()
    report = await mod.run_benchmark(iterations=2)
    assert len(report.fixtures) == 3
    names = {fx.fixture for fx in report.fixtures}
    assert names == {"chitchat", "scam_risk", "reminder"}
    scam = next(f for f in report.fixtures if f.fixture == "scam_risk")
    assert scam.blocked_by_risk_count == 2


def test_main_exit_zero_with_baseline(tmp_path, monkeypatch):
    mod = _load_latency_bench()
    report = __import__("asyncio").run(mod.run_benchmark(iterations=+2))
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(mod.baseline_from_report(report)), encoding="utf-8")

    async def stable_benchmark(iterations):
        assert iterations == 2
        return report

    monkeypatch.setattr(mod, "run_benchmark", stable_benchmark)
    code = mod.main(["--iterations", "2", "--baseline", str(baseline_path)])
    assert code == 0
