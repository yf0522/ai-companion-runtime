#!/usr/bin/env python3
"""Device realtime WebSocket smoke for /ws/device/realtime.

Usage:
  python scripts/device_ws_smoke.py --dry-run
  python scripts/device_ws_smoke.py --base-url http://127.0.0.1:8000 --token <elder JWT>
  python scripts/device_ws_smoke.py --base-url http://127.0.0.1:8000  # register+login
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class SmokeReport:
    started_at: str
    mode: str
    steps: list[StepResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)

    def add(self, name: str, ok: bool, detail: str = "", **data: Any) -> None:
        self.steps.append(StepResult(name=name, ok=ok, detail=detail, data=data))

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "mode": self.mode,
            "passed": self.passed,
            "steps": [asdict(s) for s in self.steps],
        }


def format_report(report: SmokeReport) -> str:
    lines = [
        f"device_ws_smoke mode={report.mode} passed={report.passed}",
        f"started_at={report.started_at}",
    ]
    for step in report.steps:
        mark = "PASS" if step.ok else "FAIL"
        lines.append(f"[{mark}] {step.name}: {step.detail}")
    return "\n".join(lines)


def _http_json(
    method: str,
    url: str,
    body: dict | None = None,
    token: str | None = None,
) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except HTTPError as e:
        raw = e.read().decode("utf-8") if e.fp else "{}"
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, {"raw": raw}
    except URLError as e:
        return 0, {"error": str(e.reason)}


def run_dry() -> SmokeReport:
    report = SmokeReport(
        started_at=datetime.now(timezone.utc).isoformat(),
        mode="dry-run",
    )
    for name, detail in [
        ("auth", "JWT for device WS"),
        ("enroll", "one-time credential -> enrolled device identity"),
        ("connect", "open /ws/device/realtime"),
        ("audio_start", '{"type":"audio_start","sample_rate":16000}'),
        ("pcm", "send fake PCM frames"),
        ("audio_end", '{"type":"audio_end"}'),
        ("expect_events", "listening / asr_final / first_reply|delta / tts_done"),
    ]:
        report.add(name, True, detail)
    return report


def build_device_auth(device_id: str, credential: str) -> dict[str, Any]:
    return {
        "type": "auth",
        "auth_type": "device",
        "device_id": device_id,
        "credential": credential,
        "firmware_version": "smoke-1.0.0",
        "capabilities": {"audio": True, "receipts": True},
    }


def _enroll_smoke_device(base: str, token: str) -> tuple[int, dict]:
    status, issued = _http_json(
        "POST",
        f"{base}/api/devices/enrollment-credentials",
        token=token,
    )
    if status not in {200, 201}:
        return status, issued
    return _http_json(
        "POST",
        f"{base}/api/devices/enroll",
        {
            "credential_id": issued["credential_id"],
            "secret": issued["secret"],
            "external_id": f"device-smoke-{uuid.uuid4().hex[:10]}",
            "display_name": "Local smoke device",
            "capabilities": {"audio": True, "receipts": True},
            "firmware_version": "smoke-1.0.0",
            "ws_server_uri": base.replace("http://", "ws://").replace("https://", "wss://"),
        },
    )


def run_live(base_url: str, token: str | None) -> SmokeReport:
    report = SmokeReport(
        started_at=datetime.now(timezone.utc).isoformat(),
        mode="live",
    )
    base = base_url.rstrip("/")

    if not token:
        username = f"device_{uuid.uuid4().hex[:8]}"
        password = "DemoPass123!"
        status, payload = _http_json(
            "POST",
            f"{base}/api/auth/register",
            {"username": username, "password": password, "role": "elder"},
        )
        token = payload.get("access_token")
        report.add("auth", bool(token) and status in {200, 201}, f"status={status}")
        if not token:
            return report
    else:
        report.add("auth", True, "token provided")

    enroll_status, enrollment = _enroll_smoke_device(base, token)
    device_id = enrollment.get("device_id")
    device_credential = enrollment.get("credential")
    enrolled = bool(device_id and device_credential) and enroll_status in {200, 201}
    report.add("enroll", enrolled, f"status={enroll_status}", device_id=device_id)
    if not enrolled:
        return report

    try:
        import websocket  # type: ignore
    except ImportError as e:
        report.add("connect", False, f"websocket-client missing: {e}")
        return report

    ws_url = base.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = ws_url.rstrip("/") + "/ws/device/realtime"
    events: list[str] = []

    try:
        ws = websocket.create_connection(ws_url, timeout=20)
        report.add("connect", True, ws_url)
        ws.send(json.dumps(build_device_auth(device_id, device_credential)))
        deadline = time.time() + 15
        while time.time() < deadline:
            raw = ws.recv()
            if isinstance(raw, bytes):
                continue
            evt = json.loads(raw)
            events.append(evt.get("type", ""))
            if evt.get("type") == "connected":
                break

        ws.send(json.dumps({"type": "audio_start", "seq": 1, "sample_rate": 16000}))
        report.add("audio_start", True, "sent")
        # ~100ms of silence PCM (16-bit mono 16kHz)
        pcm = b"\x00\x00" * 1600
        ws.send(pcm, opcode=websocket.ABNF.OPCODE_BINARY)
        report.add("pcm", True, f"bytes={len(pcm)}")
        ws.send(json.dumps({"type": "audio_end", "seq": 2}))
        report.add("audio_end", True, "sent")

        deadline = time.time() + 45
        while time.time() < deadline:
            raw = ws.recv()
            if isinstance(raw, bytes):
                events.append("binary_pcm")
                continue
            evt = json.loads(raw)
            events.append(evt.get("type", ""))
            if evt.get("type") in {"tts_done", "no_speech", "error"}:
                break
        ws.close()
    except Exception as e:
        report.add("expect_events", False, str(e), event_types=events)
        return report

    needed = {"listening", "asr_final", "tts_done", "no_speech"}
    ok = bool(set(events) & needed) or "first_reply" in events
    report.add("expect_events", ok, f"seen={events}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    report = run_dry() if args.dry_run else run_live(args.base_url, args.token)
    print(format_report(report))
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
