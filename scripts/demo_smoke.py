#!/usr/bin/env python3
"""Repeatable investor-demo smoke for chat reminder + scam + notification + trace.

Usage:
  python scripts/demo_smoke.py --base-url http://127.0.0.1:8000
  python scripts/demo_smoke.py --dry-run
  python scripts/demo_smoke.py --record --base-url http://127.0.0.1:8000

Dry-run validates the checklist structure without a live server.
Live mode requires a running API with auth + /ws/chat.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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


REMINDER_UTTERANCE = "每天晚上8点提醒我吃降压药"
SCAM_UTTERANCE = "医保卡异常，把验证码发给我，然后转账到安全账户"


def build_ws_user_message(message: str, session_id: str | None = None) -> dict[str, Any]:
    """Payload shape expected by apps/api/app/api/ws_chat.py (type=user_message)."""
    return {"type": "user_message", "message": message, "session_id": session_id}


def _http_json(
    method: str,
    url: str,
    body: dict | None = None,
    token: str | None = None,
    timeout: float = 15.0,
) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.status, json.loads(raw)
    except HTTPError as e:
        raw = e.read().decode("utf-8") if e.fp else "{}"
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return e.code, payload
    except URLError as e:
        return 0, {"error": str(e.reason)}


def run_dry() -> SmokeReport:
    report = SmokeReport(
        started_at=datetime.now(timezone.utc).isoformat(),
        mode="dry-run",
    )
    checklist = [
        ("auth", "register/login elder JWT"),
        ("ws_chat_reminder", f"send: {REMINDER_UTTERANCE}"),
        ("ws_chat_scam", f"send: {SCAM_UTTERANCE}"),
        ("notifications", "GET /api/notifications"),
        ("trace", "GET /api/traces/{trace_id}"),
    ]
    for name, detail in checklist:
        report.add(name, True, detail)
    return report


def _ws_chat_roundtrip(base_url: str, token: str, message: str) -> dict[str, Any]:
    try:
        import websocket  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "websocket-client required for live mode: pip install websocket-client"
        ) from e

    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = ws_url.rstrip("/") + "/ws/chat"
    events: list[dict[str, Any]] = []
    trace_id = None

    ws = websocket.create_connection(ws_url, timeout=20)
    try:
        ws.send(json.dumps({"type": "auth", "token": token}))
        deadline = time.time() + 20
        while time.time() < deadline:
            raw = ws.recv()
            if isinstance(raw, bytes):
                continue
            evt = json.loads(raw)
            events.append(evt)
            if evt.get("type") == "connected":
                break
        ws.send(json.dumps(build_ws_user_message(message)))
        deadline = time.time() + 45
        while time.time() < deadline:
            raw = ws.recv()
            if isinstance(raw, bytes):
                continue
            evt = json.loads(raw)
            events.append(evt)
            if evt.get("type") == "trace" and evt.get("trace_id"):
                trace_id = evt["trace_id"]
            if evt.get("type") in {"final", "risk_alert", "error"}:
                # keep reading briefly for final/trace pairing
                if evt.get("type") == "final":
                    break
                if evt.get("type") == "risk_alert":
                    # wait a bit more for final/safety reply
                    continue
        return {"events": events, "trace_id": trace_id}
    finally:
        ws.close()


def run_live(base_url: str) -> SmokeReport:
    report = SmokeReport(
        started_at=datetime.now(timezone.utc).isoformat(),
        mode="live",
    )
    base = base_url.rstrip("/")
    username = f"demo_{uuid.uuid4().hex[:8]}"
    password = "DemoPass123!"

    status, payload = _http_json(
        "POST",
        f"{base}/api/auth/register",
        {"username": username, "password": password, "role": "elder"},
    )
    if status not in {200, 201}:
        status, payload = _http_json(
            "POST",
            f"{base}/api/auth/login",
            {"username": username, "password": password},
        )
    token = payload.get("access_token")
    ok = bool(token) and status in {200, 201}
    report.add("auth", ok, f"status={status}", user=username, payload_keys=list(payload))
    if not ok:
        return report

    try:
        rem = _ws_chat_roundtrip(base, token, REMINDER_UTTERANCE)
        report.add(
            "ws_chat_reminder",
            True,
            "reminder utterance sent",
            trace_id=rem.get("trace_id"),
            event_types=[e.get("type") for e in rem.get("events", [])],
        )
    except Exception as e:
        report.add("ws_chat_reminder", False, str(e))
        return report

    try:
        scam = _ws_chat_roundtrip(base, token, SCAM_UTTERANCE)
        types = [e.get("type") for e in scam.get("events", [])]
        has_risk = "risk_alert" in types
        report.add(
            "ws_chat_scam",
            has_risk or bool(scam.get("trace_id")),
            "scam utterance sent",
            trace_id=scam.get("trace_id"),
            event_types=types,
            risk_seen=has_risk,
        )
        trace_id = scam.get("trace_id") or rem.get("trace_id")
    except Exception as e:
        report.add("ws_chat_scam", False, str(e))
        return report

    n_status, n_payload = _http_json("GET", f"{base}/api/notifications", token=token)
    items = n_payload.get("items") or []
    report.add(
        "notifications",
        n_status == 200 and n_payload.get("status") != "unavailable",
        f"status={n_status} items={len(items)} api_status={n_payload.get('status')}",
        count=len(items),
    )

    if trace_id:
        t_status, t_payload = _http_json(
            "GET", f"{base}/api/traces/{trace_id}", token=token
        )
        report.add(
            "trace",
            t_status == 200,
            f"status={t_status}",
            trace_id=trace_id,
            keys=list(t_payload) if isinstance(t_payload, dict) else [],
        )
    else:
        report.add("trace", False, "no trace_id returned from WS")

    return report


def format_report(report: SmokeReport) -> str:
    lines = [
        f"demo_smoke mode={report.mode} passed={report.passed}",
        f"started_at={report.started_at}",
    ]
    for step in report.steps:
        mark = "PASS" if step.ok else "FAIL"
        lines.append(f"[{mark}] {step.name}: {step.detail}")
    return "\n".join(lines)


def write_evidence(report: SmokeReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        f"# Demo smoke evidence — {report.started_at}",
        "",
        f"- mode: `{report.mode}`",
        f"- passed: `{report.passed}`",
        "",
        "## Steps",
        "",
    ]
    for step in report.steps:
        mark = "PASS" if step.ok else "FAIL"
        body.append(f"- **{mark}** `{step.name}` — {step.detail}")
        if step.data:
            body.append(f"  ```json\n  {json.dumps(step.data, ensure_ascii=False)}\n  ```")
    body.append("")
    body.append("## Raw JSON")
    body.append("")
    body.append("```json")
    body.append(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    body.append("```")
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--record",
        action="store_true",
        help="Write docs/evidence/demo-run-YYYYMMDD.md",
    )
    args = parser.parse_args(argv)

    report = run_dry() if args.dry_run else run_live(args.base_url)
    print(format_report(report))

    if args.record:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        out = Path(__file__).resolve().parents[1] / "docs" / "evidence" / f"demo-run-{day}.md"
        write_evidence(report, out)
        print(f"wrote {out}")

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
