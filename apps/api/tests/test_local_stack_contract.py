from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def stack_repo(tmp_path: Path) -> dict[str, Path | dict[str, str]]:
    root = tmp_path / "repo"
    fake_bin = tmp_path / "fake-bin"
    state = tmp_path / "fake-state"
    run_dir = tmp_path / "run"
    log = tmp_path / "commands.log"
    for path in (
        root / "scripts",
        root / "apps" / "api",
        root / "apps" / "web",
        root / "apps" / "pi-sidecar",
        fake_bin,
        state,
        run_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    script = root / "scripts" / "local_stack.sh"
    shutil.copy2(REPO_ROOT / "scripts" / "local_stack.sh", script)
    script.chmod(0o755)

    _write_executable(
        fake_bin / "git",
        "#!/usr/bin/env bash\necho deadbee\n",
    )
    _write_executable(
        fake_bin / "sleep",
        "#!/usr/bin/env bash\n/bin/sleep 0.02\n",
    )
    _write_executable(
        fake_bin / "python3",
        """#!/usr/bin/env bash
echo "python3 $*" >>"$FAKE_COMMAND_LOG"
exec "$FAKE_REAL_PYTHON" "$@"
""",
    )
    _write_executable(
        fake_bin / "uv",
        """#!/usr/bin/env bash
echo "uv $*" >>"$FAKE_COMMAND_LOG"
exit 0
""",
    )
    for runtime in ("node", "npm"):
        _write_executable(
            fake_bin / runtime,
            f"#!/usr/bin/env bash\necho \"{runtime} $*\" >>\"$FAKE_COMMAND_LOG\"\nexit 0\n",
        )

    _write_executable(
        fake_bin / "lsof",
        r'''#!/usr/bin/env bash
printf 'lsof' >>"$FAKE_COMMAND_LOG"
printf ' <%s>' "$@" >>"$FAKE_COMMAND_LOG"
printf '\n' >>"$FAKE_COMMAND_LOG"
port=""
for arg in "$@"; do
  case "$arg" in
    *iTCP:*) port="${arg##*:}" ;;
  esac
done
if [[ -n "${FAKE_FORCE_DOWN_PORT:-}" && "$port" == "$FAKE_FORCE_DOWN_PORT" ]]; then
  exit 1
fi
if [[ "${FAKE_ALL_LISTENING:-0}" == "1" || -f "$FAKE_STATE_DIR/$port.listen" ]]; then
  case " $* " in
    *" -t"*|*"-tiTCP"*) echo 424242 ;;
  esac
  exit 0
fi
exit 1
''',
    )
    _write_executable(
        fake_bin / "setsid",
        r'''#!/usr/bin/env bash
printf 'setsid' >>"$FAKE_COMMAND_LOG"
printf ' <%s>' "$@" >>"$FAKE_COMMAND_LOG"
printf '\n' >>"$FAKE_COMMAND_LOG"
joined=" $* "
case "$joined" in
  *" server.mjs "*) touch "$FAKE_STATE_DIR/$FAKE_PI_PORT.listen" ;;
  *" uvicorn "*) touch "$FAKE_STATE_DIR/$FAKE_API_PORT.listen" ;;
  *" npm run dev "*) touch "$FAKE_STATE_DIR/$FAKE_WEB_PORT.listen" ;;
esac
exit 0
''',
    )
    _write_executable(
        fake_bin / "tmux",
        r'''#!/usr/bin/env bash
printf 'tmux' >>"$FAKE_COMMAND_LOG"
printf ' <%s>' "$@" >>"$FAKE_COMMAND_LOG"
printf '\n' >>"$FAKE_COMMAND_LOG"
case "${1:-}" in
  has-session)
    session="${3#=companion-}"
    [[ -f "$FAKE_STATE_DIR/$session.session" ]]
    ;;
  new-session)
    session=""
    previous=""
    for arg in "$@"; do
      if [[ "$previous" == "-s" ]]; then session="${arg#companion-}"; fi
      previous="$arg"
    done
    touch "$FAKE_STATE_DIR/$session.session"
    case "$session" in
      api) touch "$FAKE_STATE_DIR/$FAKE_API_PORT.listen" ;;
      web) touch "$FAKE_STATE_DIR/$FAKE_WEB_PORT.listen" ;;
      pi) touch "$FAKE_STATE_DIR/$FAKE_PI_PORT.listen" ;;
    esac
    ;;
  list-panes) echo 424242 ;;
  kill-session)
    session="${3#=companion-}"
    rm -f "$FAKE_STATE_DIR/$session.session"
    ;;
esac
''',
    )
    _write_executable(
        fake_bin / "curl",
        r'''#!/usr/bin/env bash
printf 'curl' >>"$FAKE_COMMAND_LOG"
printf ' <%s>' "$@" >>"$FAKE_COMMAND_LOG"
printf '\n' >>"$FAKE_COMMAND_LOG"
output=""
write_code=0
url=""
previous=""
for arg in "$@"; do
  if [[ "$previous" == "-o" ]]; then output="$arg"; fi
  if [[ "$previous" == "-w" ]]; then write_code=1; fi
  case "$arg" in http://*|https://*) url="$arg" ;; esac
  previous="$arg"
done
body='{}'
code=200
if [[ "$url" == */ready ]]; then
  body="${FAKE_READINESS_JSON-}"
  [[ -n "$body" ]] || body='{}'
  code="${FAKE_READINESS_HTTP_CODE:-200}"
fi
if [[ -n "$output" && "$output" != "/dev/null" ]]; then
  printf '%s' "$body" >"$output"
elif [[ -z "$output" ]]; then
  printf '%s' "$body"
fi
if [[ "$write_code" -eq 1 ]]; then printf '%s' "$code"; fi
''',
    )

    clean_env = os.environ.copy()
    for key in (
        "LOCAL_STACK_PROFILE",
        "API_PORT",
        "WEB_PORT",
        "PI_PORT",
        "PI_SIDECAR_PORT",
        "REDIS_PASSWORD",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "TOOL_BRIDGE_TOKEN",
        "LOCAL_STACK_DISABLE_TMUX",
        "DATABASE_URL",
        "REDIS_URL",
        "CELERY_BROKER_URL",
        "CORS_ALLOWED_ORIGINS",
        "ENABLE_PI_RUNTIME",
        "PI_SIDECAR_URL",
        "TOOL_BRIDGE_URL",
        "NEXT_PUBLIC_API_URL",
        "NEXT_PUBLIC_WS_URL",
        "NEXT_PUBLIC_AGENT_RUNTIME",
    ):
        clean_env.pop(key, None)
    clean_env.update(
        {
            "PATH": f"{fake_bin}:{clean_env['PATH']}",
            "LOCAL_STACK_RUN_DIR": str(run_dir),
            "FAKE_COMMAND_LOG": str(log),
            "FAKE_STATE_DIR": str(state),
            "FAKE_REAL_PYTHON": sys.executable,
            "FAKE_API_PORT": "8001",
            "FAKE_WEB_PORT": "3000",
            "FAKE_PI_PORT": "8787",
            "FAKE_READINESS_JSON": _readiness_payload("ready"),
            "FAKE_READINESS_HTTP_CODE": "200",
            "HOME": str(tmp_path / "home"),
        }
    )
    return {
        "root": root,
        "script": script,
        "run_dir": run_dir,
        "state": state,
        "log": log,
        "env": clean_env,
    }


def _readiness_payload(status: str) -> str:
    check_status = status
    check_id = "database"
    if status == "degraded":
        check_id = "worker"
    elif status == "unsafe_to_serve":
        check_id = "redis"
    return json.dumps(
        {
            "contract_version": "platform-readiness.v1",
            "scope": "platform",
            "status": status,
            "checked_at": "2026-07-12T08:30:00Z",
            "duration_ms": 3.2,
            "checks": {check_id: {"status": check_status}},
        }
    )


def _readiness_with_checks(status: str, check_statuses: dict[str, str], **overrides: object) -> str:
    payload = {
        "contract_version": "platform-readiness.v1",
        "scope": "platform",
        "status": status,
        "checked_at": "2026-07-12T08:30:00Z",
        "duration_ms": 3.2,
        "checks": {
            check_id: {"status": check_status}
            for check_id, check_status in check_statuses.items()
        },
    }
    payload.update(overrides)
    return json.dumps(payload)


def _run(
    stack_repo: dict[str, Path | dict[str, str]],
    command: str,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    env = dict(stack_repo["env"])
    env.update(overrides)
    return subprocess.run(
        [str(stack_repo["script"]), command],
        cwd=stack_repo["root"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def test_profile_persists_only_allowlisted_values_and_drives_later_commands(stack_repo):
    result = _run(
        stack_repo,
        "start",
        API_PORT="8101",
        WEB_PORT="3001",
        PI_SIDECAR_PORT="8877",
        FAKE_API_PORT="8101",
        FAKE_WEB_PORT="3001",
        FAKE_PI_PORT="8877",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    profile = (stack_repo["run_dir"] / "profile.env").read_text(encoding="utf-8")
    assert profile == (
        "LOCAL_STACK_PROFILE=native\n"
        "API_PORT=8101\n"
        "WEB_PORT=3001\n"
        "PI_SIDECAR_PORT=8877\n"
    )
    assert not any(token in profile for token in ("PASSWORD", "TOKEN", "KEY", "URL", "DEMO_"))

    stack_repo["log"].write_text("", encoding="utf-8")
    status = _run(
        stack_repo,
        "status",
        FAKE_API_PORT="8101",
        FAKE_WEB_PORT="3001",
        FAKE_PI_PORT="8877",
    )
    assert status.returncode == 0
    assert "web :3001" in status.stdout
    assert "api :8101" in status.stdout
    assert "pi :8877" in status.stdout

    overridden = _run(
        stack_repo,
        "status",
        WEB_PORT="3100",
        FAKE_API_PORT="8101",
        FAKE_WEB_PORT="3100",
        FAKE_PI_PORT="8877",
        FAKE_ALL_LISTENING="1",
    )
    assert overridden.returncode == 0
    assert "web :3100" in overridden.stdout

    stack_repo["log"].write_text("", encoding="utf-8")
    stopped = _run(
        stack_repo,
        "stop",
        FAKE_API_PORT="8101",
        FAKE_WEB_PORT="3001",
        FAKE_PI_PORT="8877",
        FAKE_ALL_LISTENING="1",
    )
    assert stopped.returncode == 0
    stop_log = stack_repo["log"].read_text(encoding="utf-8")
    assert "TCP:3001" in stop_log
    assert "TCP:3000" not in stop_log


def test_malicious_duplicate_profile_is_data_not_code(stack_repo, tmp_path):
    marker = tmp_path / "profile-executed"
    (stack_repo["run_dir"] / "profile.env").write_text(
        "LOCAL_STACK_PROFILE=native\n"
        "API_PORT=8001\n"
        f"WEB_PORT=$(touch {marker})\n"
        "WEB_PORT=3001\n"
        "PI_SIDECAR_PORT=8787\n",
        encoding="utf-8",
    )

    result = _run(stack_repo, "status", FAKE_ALL_LISTENING="1")

    assert result.returncode == 0
    assert not marker.exists()
    assert "ignoring invalid local stack profile" in result.stderr
    assert "web :3000" in result.stdout


@pytest.mark.parametrize(
    "name,value",
    [("API_PORT", "0"), ("WEB_PORT", "65536"), ("PI_SIDECAR_PORT", "8x")],
)
def test_explicit_invalid_ports_are_rejected(stack_repo, name, value):
    result = _run(stack_repo, "status", **{name: value})

    assert result.returncode == 2
    assert f"Invalid {name}" in result.stderr


@pytest.mark.parametrize(
    ("payload", "http_code", "extra_env", "expected_code", "expected_text"),
    [
        (_readiness_payload("ready"), "200", {}, 0, "platform readiness: ready"),
        (_readiness_payload("degraded"), "200", {}, 0, "limitations: worker"),
        (_readiness_payload("unsafe_to_serve"), "503", {}, 1, "unsafe checks: redis"),
        ("not-json", "200", {}, 1, "payload is invalid or unknown"),
        (
            _readiness_payload("mystery"),
            "200",
            {},
            1,
            "payload is invalid or unknown",
        ),
        (
            _readiness_payload("ready"),
            "200",
            {"FAKE_FORCE_DOWN_PORT": "8787"},
            1,
            "pi is not listening on :8787",
        ),
    ],
)
def test_doctor_uses_process_and_readiness_truth(
    stack_repo,
    payload,
    http_code,
    extra_env,
    expected_code,
    expected_text,
):
    result = _run(
        stack_repo,
        "doctor",
        FAKE_ALL_LISTENING="1",
        FAKE_READINESS_JSON=payload,
        FAKE_READINESS_HTTP_CODE=http_code,
        **extra_env,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == expected_code, combined
    assert expected_text in combined
    if expected_code:
        assert "Doctor passed" not in combined


@pytest.mark.parametrize(
    "payload",
    [
        _readiness_with_checks("ready", {"database": "ready"}, contract_version="wrong.v1"),
        _readiness_with_checks("ready", {"database": "ready"}, contract_version=None),
        _readiness_with_checks("ready", {"database": "degraded"}),
        _readiness_with_checks("ready", {"database": "unsafe_to_serve"}),
        _readiness_with_checks("degraded", {"database": "unsafe_to_serve"}),
        _readiness_with_checks("degraded", {"database": "ready"}),
    ],
)
def test_doctor_rejects_wrong_contract_and_optimistic_or_inconsistent_aggregate(
    stack_repo,
    payload,
):
    result = _run(
        stack_repo,
        "doctor",
        FAKE_ALL_LISTENING="1",
        FAKE_READINESS_JSON=payload,
        FAKE_READINESS_HTTP_CODE="200",
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "readiness payload is invalid or unknown" in result.stderr
    assert "Doctor passed" not in result.stdout


def test_env_precedence_keeps_caller_then_profile_then_dotenv_aligned(stack_repo):
    root = stack_repo["root"]
    (root / ".env").write_text(
        "API_PORT=9101\nWEB_PORT=4101\nPI_SIDECAR_PORT=9777\nREDIS_PASSWORD=dotenv-secret\n",
        encoding="utf-8",
    )
    (stack_repo["run_dir"] / "profile.env").write_text(
        "LOCAL_STACK_PROFILE=native\nAPI_PORT=8201\nWEB_PORT=3201\nPI_SIDECAR_PORT=8877\n",
        encoding="utf-8",
    )

    result = _run(
        stack_repo,
        "start",
        WEB_PORT="3301",
        REDIS_PASSWORD="caller-secret",
        FAKE_API_PORT="8201",
        FAKE_WEB_PORT="3301",
        FAKE_PI_PORT="8877",
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "API  http://127.0.0.1:8201" in result.stdout
    assert "Web  http://127.0.0.1:3301" in result.stdout
    assert "Pi   http://127.0.0.1:8877" in result.stdout
    command_log = stack_repo["log"].read_text(encoding="utf-8")
    assert "--port 8201" in command_log
    assert "-p 3301" in command_log
    assert "PI_SIDECAR_PORT=8877" in command_log
    assert "caller-secret" in command_log
    assert "dotenv-secret" not in command_log
    assert "9101" not in command_log
    assert "4101" not in command_log
    assert "9777" not in command_log


@pytest.mark.parametrize("disable_tmux", [False, True], ids=["tmux", "no-tmux"])
@pytest.mark.parametrize("password", [None, "supplied-secret"], ids=["passwordless", "password"])
def test_start_propagates_redis_password_and_pi_port_without_persisting_secrets(
    stack_repo,
    disable_tmux,
    password,
):
    overrides = {
        "PI_SIDECAR_PORT": "9876",
        "FAKE_PI_PORT": "9876",
    }
    if disable_tmux:
        overrides["LOCAL_STACK_DISABLE_TMUX"] = "1"
    if password is not None:
        overrides["REDIS_PASSWORD"] = password

    result = _run(stack_repo, "start", **overrides)

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    command_log = stack_repo["log"].read_text(encoding="utf-8")
    expected_password = password or ""
    if disable_tmux:
        assert f"<REDIS_PASSWORD={expected_password}>" in command_log
        assert "<PI_SIDECAR_PORT=9876>" in command_log
    else:
        rendered_password = expected_password if expected_password else "''"
        assert f"REDIS_PASSWORD={rendered_password}" in command_log
        assert "PI_SIDECAR_PORT=9876" in command_log
    profile = (stack_repo["run_dir"] / "profile.env").read_text(encoding="utf-8")
    assert "REDIS_PASSWORD" not in profile
    assert "supplied-secret" not in profile
    assert "PI_SIDECAR_PORT=9876" in profile


@pytest.mark.parametrize(
    ("status", "http_code", "expected_code"),
    [("degraded", "200", 0), ("unsafe_to_serve", "503", 1)],
)
def test_start_finishes_through_doctor_without_hard_coded_ready(
    stack_repo,
    status,
    http_code,
    expected_code,
):
    result = _run(
        stack_repo,
        "start",
        FAKE_READINESS_JSON=_readiness_payload(status),
        FAKE_READINESS_HTTP_CODE=http_code,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == expected_code, combined
    assert "READY" not in combined
    assert f"platform readiness: {status}" in combined
    if expected_code:
        assert "Start incomplete: platform readiness did not pass." in combined
