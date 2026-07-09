"""Unit tests for demo smoke report helpers (no live server required)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load(name: str, filename: str):
    path = Path(__file__).resolve().parents[3] / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_demo_smoke_dry_run_passes():
    mod = _load("demo_smoke", "demo_smoke.py")
    report = mod.run_dry()
    assert report.passed
    names = [s.name for s in report.steps]
    assert names == [
        "auth",
        "ws_chat_reminder",
        "ws_chat_scam",
        "notifications",
        "trace",
    ]
    text = mod.format_report(report)
    assert "passed=True" in text
    assert "[PASS] auth" in text


def test_device_ws_smoke_dry_run_passes():
    mod = _load("device_ws_smoke", "device_ws_smoke.py")
    report = mod.run_dry()
    assert report.passed
    assert any(s.name == "audio_start" for s in report.steps)
    assert "device_ws_smoke" in mod.format_report(report)


def test_demo_smoke_ws_user_message_payload_matches_backend():
    mod = _load("demo_smoke_payload", "demo_smoke.py")
    payload = mod.build_ws_user_message("每天晚上8点提醒我吃降压药")
    assert payload["type"] == "user_message"
    assert "message" in payload
    assert "content" not in payload
    assert payload["message"] == "每天晚上8点提醒我吃降压药"


def test_demo_smoke_main_dry_run_exit_zero(tmp_path):
    mod = _load("demo_smoke_main", "demo_smoke.py")
    code = mod.main(["--dry-run"])
    assert code == 0

    report = mod.run_dry()
    out = tmp_path / "demo-run.md"
    mod.write_evidence(report, out)
    text = out.read_text(encoding="utf-8")
    assert "passed: `True`" in text
    assert "ws_chat_scam" in text
