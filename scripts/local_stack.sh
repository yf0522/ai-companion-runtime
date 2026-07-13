#!/usr/bin/env bash
# Local demo stack: API :8001, Web :3000, Pi sidecar :8787
# Usage: ./scripts/local_stack.sh {start|stop|restart|status|doctor}
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="${LOCAL_STACK_RUN_DIR:-$ROOT/.local-stack}"
PROFILE_FILE="$RUN_DIR/profile.env"

_PERSISTED_LOCAL_STACK_PROFILE=""
_PERSISTED_API_PORT=""
_PERSISTED_WEB_PORT=""
_PERSISTED_PI_SIDECAR_PORT=""

_is_valid_port() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] && [[ "${#value}" -le 5 ]] && ((10#$value >= 1 && 10#$value <= 65535))
}

_read_profile() {
  [[ -f "$PROFILE_FILE" ]] || return 0

  local line key value invalid=0
  local seen_profile=0 seen_api=0 seen_web=0 seen_pi=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    if [[ "$line" != *=* ]]; then
      invalid=1
      continue
    fi
    key="${line%%=*}"
    value="${line#*=}"
    case "$key" in
      LOCAL_STACK_PROFILE)
        if [[ "$seen_profile" -eq 1 || "$value" != "native" ]]; then
          invalid=1
        else
          seen_profile=1
          _PERSISTED_LOCAL_STACK_PROFILE="$value"
        fi
        ;;
      API_PORT)
        if [[ "$seen_api" -eq 1 ]] || ! _is_valid_port "$value"; then
          invalid=1
        else
          seen_api=1
          _PERSISTED_API_PORT="$value"
        fi
        ;;
      WEB_PORT)
        if [[ "$seen_web" -eq 1 ]] || ! _is_valid_port "$value"; then
          invalid=1
        else
          seen_web=1
          _PERSISTED_WEB_PORT="$value"
        fi
        ;;
      PI_SIDECAR_PORT)
        if [[ "$seen_pi" -eq 1 ]] || ! _is_valid_port "$value"; then
          invalid=1
        else
          seen_pi=1
          _PERSISTED_PI_SIDECAR_PORT="$value"
        fi
        ;;
      *) invalid=1 ;;
    esac
  done <"$PROFILE_FILE"

  if [[ "$invalid" -eq 1 || "$seen_profile" -ne 1 || "$seen_api" -ne 1 || "$seen_web" -ne 1 || "$seen_pi" -ne 1 ]]; then
    echo "WARN: ignoring invalid local stack profile $PROFILE_FILE" >&2
    _PERSISTED_LOCAL_STACK_PROFILE=""
    _PERSISTED_API_PORT=""
    _PERSISTED_WEB_PORT=""
    _PERSISTED_PI_SIDECAR_PORT=""
  fi
}

mkdir -p "$RUN_DIR"
_read_profile

# Capture the caller-owned values before loading developer .env files. These
# values have the highest precedence and must survive any conflicting entries.
_CALLER_LOCAL_STACK_PROFILE_SET="${LOCAL_STACK_PROFILE+x}"
_CALLER_LOCAL_STACK_PROFILE="${LOCAL_STACK_PROFILE-}"
_CALLER_API_PORT_SET="${API_PORT+x}"
_CALLER_API_PORT="${API_PORT-}"
_CALLER_WEB_PORT_SET="${WEB_PORT+x}"
_CALLER_WEB_PORT="${WEB_PORT-}"
_CALLER_PI_SIDECAR_PORT_SET="${PI_SIDECAR_PORT+x}"
_CALLER_PI_SIDECAR_PORT="${PI_SIDECAR_PORT-}"
_CALLER_PI_PORT_SET="${PI_PORT+x}"
_CALLER_PI_PORT="${PI_PORT-}"
_CALLER_REDIS_PASSWORD_SET="${REDIS_PASSWORD+x}"
_CALLER_REDIS_PASSWORD="${REDIS_PASSWORD-}"

set -a
# Optional developer-owned environment files have lower precedence than the
# caller and persisted local-stack profile, but higher precedence than defaults.
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && . "$ROOT/.env"
# shellcheck disable=SC1091
[[ -f "$ROOT/apps/api/.env" ]] && . "$ROOT/apps/api/.env"
set +a

if [[ "$_CALLER_LOCAL_STACK_PROFILE_SET" == "x" ]]; then
  RESOLVED_LOCAL_STACK_PROFILE="$_CALLER_LOCAL_STACK_PROFILE"
else
  RESOLVED_LOCAL_STACK_PROFILE="${_PERSISTED_LOCAL_STACK_PROFILE:-${LOCAL_STACK_PROFILE:-native}}"
fi
if [[ "$RESOLVED_LOCAL_STACK_PROFILE" != "native" ]]; then
  echo "Invalid LOCAL_STACK_PROFILE: expected native" >&2
  exit 2
fi

if [[ "$_CALLER_API_PORT_SET" == "x" ]]; then
  RESOLVED_API_PORT="$_CALLER_API_PORT"
else
  RESOLVED_API_PORT="${_PERSISTED_API_PORT:-${API_PORT:-8001}}"
fi
if [[ "$_CALLER_WEB_PORT_SET" == "x" ]]; then
  RESOLVED_WEB_PORT="$_CALLER_WEB_PORT"
else
  RESOLVED_WEB_PORT="${_PERSISTED_WEB_PORT:-${WEB_PORT:-3000}}"
fi
if [[ "$_CALLER_PI_SIDECAR_PORT_SET" == "x" ]]; then
  RESOLVED_PI_SIDECAR_PORT="$_CALLER_PI_SIDECAR_PORT"
elif [[ "$_CALLER_PI_PORT_SET" == "x" ]]; then
  # PI_PORT remains a supported invocation alias; persisted state uses the runtime's name.
  RESOLVED_PI_SIDECAR_PORT="$_CALLER_PI_PORT"
else
  RESOLVED_PI_SIDECAR_PORT="${_PERSISTED_PI_SIDECAR_PORT:-${PI_SIDECAR_PORT:-${PI_PORT:-8787}}}"
fi

for pair in \
  "API_PORT:$RESOLVED_API_PORT" \
  "WEB_PORT:$RESOLVED_WEB_PORT" \
  "PI_SIDECAR_PORT:$RESOLVED_PI_SIDECAR_PORT"; do
  name="${pair%%:*}"
  value="${pair#*:}"
  if ! _is_valid_port "$value"; then
    echo "Invalid $name: expected an integer from 1 to 65535" >&2
    exit 2
  fi
done

LOCAL_STACK_PROFILE="$RESOLVED_LOCAL_STACK_PROFILE"
API_PORT="$RESOLVED_API_PORT"
WEB_PORT="$RESOLVED_WEB_PORT"
PI_SIDECAR_PORT="$RESOLVED_PI_SIDECAR_PORT"
PI_PORT="$PI_SIDECAR_PORT"
export LOCAL_STACK_PROFILE API_PORT WEB_PORT PI_SIDECAR_PORT PI_PORT
API_HOST="127.0.0.1"
WEB_HOST="127.0.0.1"
PI_HOST="127.0.0.1"

API_URL="http://${API_HOST}:${API_PORT}"
WEB_URL="http://${WEB_HOST}:${WEB_PORT}"
PI_URL="http://${PI_HOST}:${PI_PORT}"
WS_URL="ws://${API_HOST}:${API_PORT}"
BRIDGE_URL="${TOOL_BRIDGE_URL:-${API_URL}/api}"

_persist_profile() {
  local tmp="$PROFILE_FILE.tmp.$$"
  umask 077
  {
    echo "LOCAL_STACK_PROFILE=$LOCAL_STACK_PROFILE"
    echo "API_PORT=$API_PORT"
    echo "WEB_PORT=$WEB_PORT"
    echo "PI_SIDECAR_PORT=$PI_SIDECAR_PORT"
  } >"$tmp"
  mv "$tmp" "$PROFILE_FILE"
}

_pid_file() { echo "$RUN_DIR/$1.pid"; }
_log_file() { echo "$RUN_DIR/$1.log"; }

_is_listening() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

_kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.5
    pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      # shellcheck disable=SC2086
      kill -9 $pids 2>/dev/null || true
    fi
  fi
}

_kill_process_tree() {
  local pid="$1" child
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  while IFS= read -r child; do
    [[ -n "$child" ]] && _kill_process_tree "$child"
  done < <(pgrep -P "$pid" 2>/dev/null || true)
  kill "$pid" 2>/dev/null || true
}

_kill_repo_celery_orphans() {
  local pattern="$ROOT/apps/api/.venv/bin/celery -A app.workers.celery_app"
  local pids
  pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.5
    pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      # shellcheck disable=SC2086
      kill -9 $pids 2>/dev/null || true
    fi
  fi
}

_wait_http() {
  local url="$1"
  local name="$2"
  local tries="${3:-40}"
  local i code
  for ((i = 1; i <= tries; i++)); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 1 "$url" 2>/dev/null || true)"
    code="${code:-000}"
    if [[ "$code" =~ ^[23] ]]; then
      echo "  ok  $name ($code) $url"
      return 0
    fi
    sleep 0.5
  done
  echo "  FAIL $name — last HTTP $code — see $(_log_file "$(echo "$name" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')")" >&2
  return 1
}

_seed_demo_user() {
  local user="${DEMO_USER:-demo_elder}"
  local pass="${DEMO_PASS:-demo1234}"
  local role="${DEMO_ROLE:-elder}"
  local out code
  out="$RUN_DIR/demo-auth.json"

  code="$(curl -s -o "$out" -w '%{http_code}' \
    -X POST "$API_URL/api/auth/register" \
    -H 'Content-Type: application/json' \
    --data "{\"username\":\"$user\",\"password\":\"$pass\",\"role\":\"$role\"}" \
    2>/dev/null || echo 000)"
  if [[ "$code" =~ ^20[0-9]$ ]]; then
    echo "  ok  demo user seeded ($user / $pass)"
    return 0
  fi

  if [[ "$code" == "409" ]]; then
    code="$(curl -s -o "$out" -w '%{http_code}' \
      -X POST "$API_URL/api/auth/login" \
      -H 'Content-Type: application/json' \
      --data "{\"username\":\"$user\",\"password\":\"$pass\"}" \
      2>/dev/null || echo 000)"
    if [[ "$code" =~ ^20[0-9]$ ]]; then
      echo "  ok  demo user exists ($user / $pass)"
      return 0
    fi
    echo "  WARN demo user exists but login failed with provided password ($user)" >&2
    return 1
  fi

  echo "  WARN demo user seed failed — HTTP $code — see $out" >&2
  return 1
}

_load_env() {
  export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://companion:companion_secret@127.0.0.1:5432/companion}"
  export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
  export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://127.0.0.1:6379/1}"
  # Native Redis is passwordless by default. An explicit caller/.env value still wins.
  if [[ "$_CALLER_REDIS_PASSWORD_SET" == "x" ]]; then
    REDIS_PASSWORD="$_CALLER_REDIS_PASSWORD"
  elif [[ "${REDIS_PASSWORD+x}" != "x" ]]; then
    REDIS_PASSWORD=""
  fi
  export REDIS_PASSWORD
  export CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS:-http://localhost:$WEB_PORT,http://$WEB_HOST:$WEB_PORT}"
  export ENABLE_PI_RUNTIME="${ENABLE_PI_RUNTIME:-1}"
  export PI_SIDECAR_URL="${PI_SIDECAR_URL:-$PI_URL}"
  export TOOL_BRIDGE_URL="$BRIDGE_URL"
  export NEXT_PUBLIC_API_URL="$API_URL"
  export NEXT_PUBLIC_WS_URL="$WS_URL"
  export NEXT_PUBLIC_AGENT_RUNTIME="${NEXT_PUBLIC_AGENT_RUNTIME:-pi_experimental}"
}

cmd_stop() {
  echo "Stopping local stack..."
  # Stop recorded process trees before killing tmux shells. Celery prefork
  # children can otherwise be reparented to PID 1 and keep consuming queues.
  for name in pi api web celery-worker celery-beat; do
    local pid_file pid
    pid_file="$(_pid_file "$name")"
    if [[ -f "$pid_file" ]]; then
      pid="$(cat "$pid_file")"
      _kill_process_tree "$pid"
      rm -f "$pid_file"
    fi
  done
  if command -v tmux >/dev/null 2>&1; then
    for s in companion-web companion-api companion-pi companion-celery-worker companion-celery-beat; do
      tmux has-session -t "=$s" 2>/dev/null && tmux kill-session -t "=$s" 2>/dev/null || true
    done
  fi
  _kill_repo_celery_orphans
  _kill_port "$WEB_PORT"
  _kill_port "$API_PORT"
  _kill_port "$PI_PORT"
  echo "Stopped."
}

cmd_status() {
  local pair name port url code service
  echo "Local stack status (profile $LOCAL_STACK_PROFILE, SHA $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo '?'))"
  for pair in "web:$WEB_PORT:$WEB_URL/login" "api:$API_PORT:$API_URL/health" "pi:$PI_PORT:$PI_URL/health"; do
    IFS=: read -r name port url <<<"$pair"
    if _is_listening "$port"; then
      code="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 1 "$url" 2>/dev/null || true)"
      code="${code:-000}"
      echo "  UP   $name :$port HTTP $code"
    else
      echo "  DOWN $name :$port"
    fi
  done
  for service in celery-worker celery-beat; do
    if _have_tmux && tmux has-session -t "=companion-$service" 2>/dev/null; then
      echo "  UP   $service"
    elif [[ -f "$(_pid_file "$service")" ]] && kill -0 "$(cat "$(_pid_file "$service")")" 2>/dev/null; then
      echo "  UP   $service"
    else
      echo "  DOWN $service"
    fi
  done
}

_have_tmux() {
  [[ "${LOCAL_STACK_DISABLE_TMUX:-0}" != "1" ]] && command -v tmux >/dev/null 2>&1
}

_doctor_service() {
  local name="$1" port="$2" url="$3" code
  if ! _is_listening "$port"; then
    echo "  FAIL $name is not listening on :$port" >&2
    return 1
  fi
  code="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 1 --max-time 3 "$url" 2>/dev/null || true)"
  code="${code:-000}"
  if [[ "$code" =~ ^[23] ]]; then
    echo "  ok  $name :$port HTTP $code"
    return 0
  fi
  echo "  FAIL $name :$port is unreachable over HTTP (last HTTP $code)" >&2
  return 1
}

_parse_readiness() {
  local payload_file="$1"
  python3 -c '
import json
import sys

canonical = {"ready", "degraded", "unsafe_to_serve"}
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("payload")
    if payload.get("scope") != "platform" or payload.get("contract_version") != "platform-readiness.v1":
        raise ValueError("contract")
    if not isinstance(payload.get("checked_at"), str) or not payload["checked_at"]:
        raise ValueError("timestamp")
    status = payload.get("status")
    checks = payload.get("checks")
    if status not in canonical or not isinstance(checks, dict) or not checks:
        raise ValueError("state")
    degraded = []
    unsafe = []
    for check_id, check in checks.items():
        if not isinstance(check_id, str) or not check_id or not isinstance(check, dict):
            raise ValueError("check")
        check_status = check.get("status")
        if check_status not in canonical:
            raise ValueError("check status")
        if check_status == "degraded":
            degraded.append(check_id)
        elif check_status == "unsafe_to_serve":
            unsafe.append(check_id)
    worst = "unsafe_to_serve" if unsafe else "degraded" if degraded else "ready"
    if status != worst:
        raise ValueError("aggregate")
    print(status)
    print(",".join(sorted(degraded)))
    print(",".join(sorted(unsafe)))
except (OSError, ValueError, json.JSONDecodeError, TypeError):
    sys.exit(3)
' "$payload_file"
}

cmd_doctor() {
  local ok=0 payload_file="$RUN_DIR/readiness.$$.json" code parsed status degraded_ids unsafe_ids
  echo "Local stack doctor (profile $LOCAL_STACK_PROFILE)"
  _doctor_service web "$WEB_PORT" "$WEB_URL/login" || ok=1
  _doctor_service api "$API_PORT" "$API_URL/health" || ok=1
  _doctor_service pi "$PI_PORT" "$PI_URL/health" || ok=1

  code="$(curl -sS -o "$payload_file" -w '%{http_code}' --connect-timeout 1 --max-time 5 "$API_URL/ready" 2>/dev/null || true)"
  code="${code:-000}"
  if [[ "$code" != "200" && "$code" != "503" ]]; then
    echo "  FAIL readiness endpoint is unreachable or returned unexpected HTTP $code" >&2
    rm -f "$payload_file"
    return 1
  fi
  if ! parsed="$(_parse_readiness "$payload_file" 2>/dev/null)"; then
    echo "  FAIL readiness payload is invalid or unknown" >&2
    rm -f "$payload_file"
    return 1
  fi
  rm -f "$payload_file"

  status="$(printf '%s\n' "$parsed" | sed -n '1p')"
  degraded_ids="$(printf '%s\n' "$parsed" | sed -n '2p')"
  unsafe_ids="$(printf '%s\n' "$parsed" | sed -n '3p')"
  case "$status" in
    ready)
      if [[ "$code" != "200" ]]; then
        echo "  FAIL readiness status/code mismatch (ready over HTTP $code)" >&2
        return 1
      fi
      echo "  ok  platform readiness: ready"
      ;;
    degraded)
      if [[ "$code" != "200" ]]; then
        echo "  FAIL readiness status/code mismatch (degraded over HTTP $code)" >&2
        return 1
      fi
      echo "  WARN platform readiness: degraded"
      echo "       limitations: ${degraded_ids:-reported by readiness contract}"
      ;;
    unsafe_to_serve)
      echo "  FAIL platform readiness: unsafe_to_serve" >&2
      echo "       unsafe checks: ${unsafe_ids:-unknown}" >&2
      return 1
      ;;
    *)
      echo "  FAIL readiness payload is invalid or unknown" >&2
      return 1
      ;;
  esac

  if [[ "$ok" -ne 0 ]]; then
    echo "Doctor failed: one or more required local processes are unreachable." >&2
    return 1
  fi
  echo "Doctor passed: platform state is $status."
}

_tmux_start() {
  # $1=session $2=workdir $3=command...
  local session="$1" workdir="$2"
  shift 2
  tmux has-session -t "=$session" 2>/dev/null && tmux kill-session -t "=$session" 2>/dev/null || true
  tmux new-session -d -s "$session" -c "$workdir" "$@"
  # record tmux pane pid for status
  tmux list-panes -t "$session" -F '#{pane_pid}' >"$(_pid_file "${session#companion-}")" 2>/dev/null || true
}

_start_pi() {
  local log command
  log="$(_log_file pi)"
  # tmux sessions may have stale server environments, so pass every runtime value explicitly.
  local gemini_key="${GEMINI_API_KEY:-${GOOGLE_API_KEY:-}}"
  local google_key="${GOOGLE_API_KEY:-${GEMINI_API_KEY:-}}"
  if [[ -z "$gemini_key" && -z "$google_key" ]]; then
    echo "WARN: GOOGLE_API_KEY/GEMINI_API_KEY unset — Pi sidecar will return empty replies" >&2
  fi
  if _have_tmux; then
    printf -v command \
      'env TOOL_BRIDGE_URL=%q TOOL_BRIDGE_TOKEN=%q GEMINI_API_KEY=%q GOOGLE_API_KEY=%q PI_ENABLE_TOOLS=%q PI_SIDECAR_PORT=%q node server.mjs 2>&1 | tee %q' \
      "$TOOL_BRIDGE_URL" "${TOOL_BRIDGE_TOKEN:-}" "$gemini_key" "$google_key" \
      "${PI_ENABLE_TOOLS:-1}" "$PI_SIDECAR_PORT" "$log"
    _tmux_start companion-pi "$ROOT/apps/pi-sidecar" "$command"
  else
    (
      cd "$ROOT/apps/pi-sidecar"
      (setsid env TOOL_BRIDGE_URL="$TOOL_BRIDGE_URL" TOOL_BRIDGE_TOKEN="${TOOL_BRIDGE_TOKEN:-}" \
        GEMINI_API_KEY="$gemini_key" GOOGLE_API_KEY="$google_key" PI_ENABLE_TOOLS="${PI_ENABLE_TOOLS:-1}" \
        PI_SIDECAR_PORT="$PI_SIDECAR_PORT" \
        node server.mjs >"$log" 2>&1 &)
      sleep 0.2
      lsof -tiTCP:"$PI_PORT" -sTCP:LISTEN >"$(_pid_file pi)" 2>/dev/null || true
    )
  fi
}

_start_api() {
  local log command
  log="$(_log_file api)"
  if _have_tmux; then
    printf -v command \
      'env DATABASE_URL=%q REDIS_URL=%q CELERY_BROKER_URL=%q REDIS_PASSWORD=%q CORS_ALLOWED_ORIGINS=%q ENABLE_PI_RUNTIME=%q PI_SIDECAR_URL=%q TOOL_BRIDGE_URL=%q PYTHONPATH=. uv run uvicorn app.main:app --host %q --port %q 2>&1 | tee %q' \
      "$DATABASE_URL" "$REDIS_URL" "$CELERY_BROKER_URL" "$REDIS_PASSWORD" \
      "$CORS_ALLOWED_ORIGINS" "$ENABLE_PI_RUNTIME" "$PI_SIDECAR_URL" "$TOOL_BRIDGE_URL" \
      "$API_HOST" "$API_PORT" "$log"
    _tmux_start companion-api "$ROOT/apps/api" "$command"
  else
    (
      cd "$ROOT/apps/api"
      (setsid env DATABASE_URL="$DATABASE_URL" REDIS_URL="$REDIS_URL" \
        CELERY_BROKER_URL="$CELERY_BROKER_URL" REDIS_PASSWORD="$REDIS_PASSWORD" \
        CORS_ALLOWED_ORIGINS="$CORS_ALLOWED_ORIGINS" ENABLE_PI_RUNTIME="$ENABLE_PI_RUNTIME" \
        PI_SIDECAR_URL="$PI_SIDECAR_URL" TOOL_BRIDGE_URL="$TOOL_BRIDGE_URL" PYTHONPATH=. \
        uv run uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" >"$log" 2>&1 &)
      sleep 0.2
      lsof -tiTCP:"$API_PORT" -sTCP:LISTEN >"$(_pid_file api)" 2>/dev/null || true
    )
  fi
}

_start_web() {
  local log command
  log="$(_log_file web)"
  # Keep local dev output separate from production builds and parallel review.
  # Sharing .next lets `next build` invalidate a running dev server's chunks.
  rm -rf "$ROOT/apps/web/.next-dev"
  if _have_tmux; then
    printf -v command \
      'env NEXT_DIST_DIR=.next-dev NEXT_PUBLIC_API_URL=%q NEXT_PUBLIC_WS_URL=%q NEXT_PUBLIC_AGENT_RUNTIME=%q npm run dev -- -p %q -H %q 2>&1 | tee %q' \
      "$NEXT_PUBLIC_API_URL" "$NEXT_PUBLIC_WS_URL" "$NEXT_PUBLIC_AGENT_RUNTIME" \
      "$WEB_PORT" "$WEB_HOST" "$log"
    _tmux_start companion-web "$ROOT/apps/web" "$command"
  else
    (
      cd "$ROOT/apps/web"
      (setsid env NEXT_DIST_DIR=".next-dev" NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" NEXT_PUBLIC_WS_URL="$NEXT_PUBLIC_WS_URL" NEXT_PUBLIC_AGENT_RUNTIME="$NEXT_PUBLIC_AGENT_RUNTIME" \
        npm run dev -- -p "$WEB_PORT" -H "$WEB_HOST" >"$log" 2>&1 &)
      sleep 0.2
      lsof -tiTCP:"$WEB_PORT" -sTCP:LISTEN >"$(_pid_file web)" 2>/dev/null || true
    )
  fi
}

_run_migrations() {
  echo "  ... database migrations"
  (
    cd "$ROOT/apps/api"
    PYTHONPATH=. uv run alembic upgrade head
  )
}

_start_celery() {
  [[ "${ENABLE_CELERY_TASKS:-0}" == "1" || "${ENABLE_CELERY_TASKS:-0}" == "true" ]] || return 0

  local worker_log beat_log beat_schedule worker_command beat_command
  worker_log="$(_log_file celery-worker)"
  beat_log="$(_log_file celery-beat)"
  beat_schedule="$RUN_DIR/celerybeat-schedule"

  if _have_tmux; then
    printf -v worker_command \
      'env DATABASE_URL=%q REDIS_URL=%q CELERY_BROKER_URL=%q REDIS_PASSWORD=%q PYTHONPATH=. uv run celery -A app.workers.celery_app worker -l info -c 2 -Q celery,memory,embedding,reflection 2>&1 | tee %q' \
      "$DATABASE_URL" "$REDIS_URL" "$CELERY_BROKER_URL" "$REDIS_PASSWORD" "$worker_log"
    printf -v beat_command \
      'env DATABASE_URL=%q REDIS_URL=%q CELERY_BROKER_URL=%q REDIS_PASSWORD=%q PYTHONPATH=. uv run celery -A app.workers.celery_app beat -l info -s %q 2>&1 | tee %q' \
      "$DATABASE_URL" "$REDIS_URL" "$CELERY_BROKER_URL" "$REDIS_PASSWORD" \
      "$beat_schedule" "$beat_log"
    _tmux_start companion-celery-worker "$ROOT/apps/api" "$worker_command"
    _tmux_start companion-celery-beat "$ROOT/apps/api" "$beat_command"
  else
    (
      cd "$ROOT/apps/api"
      (setsid env DATABASE_URL="$DATABASE_URL" REDIS_URL="$REDIS_URL" \
        CELERY_BROKER_URL="$CELERY_BROKER_URL" REDIS_PASSWORD="$REDIS_PASSWORD" \
        PYTHONPATH=. uv run celery -A app.workers.celery_app worker -l info -c 2 \
        -Q celery,memory,embedding,reflection >"$worker_log" 2>&1 &)
      sleep 0.2
      pgrep -f "celery -A app.workers.celery_app worker" | tail -1 >"$(_pid_file celery-worker)" || true
      (setsid env DATABASE_URL="$DATABASE_URL" REDIS_URL="$REDIS_URL" \
        CELERY_BROKER_URL="$CELERY_BROKER_URL" REDIS_PASSWORD="$REDIS_PASSWORD" \
        PYTHONPATH=. uv run celery -A app.workers.celery_app beat -l info \
        -s "$beat_schedule" >"$beat_log" 2>&1 &)
      sleep 0.2
      pgrep -f "celery -A app.workers.celery_app beat" | tail -1 >"$(_pid_file celery-beat)" || true
    )
  fi
}

cmd_start() {
  _load_env
  echo "Starting local stack in $ROOT"
  echo "  mode $LOCAL_STACK_PROFILE"
  echo "  API  $API_URL"
  echo "  Web  $WEB_URL/elder/companion"
  echo "  Pi   $PI_URL  bridge=$TOOL_BRIDGE_URL"
  echo "  logs $RUN_DIR/*.log"

  if _is_listening "$API_PORT" || _is_listening "$WEB_PORT" || _is_listening "$PI_PORT"; then
    echo "Ports in use — stopping first..."
    cmd_stop
    sleep 1
  fi

  _run_migrations
  _start_pi
  _start_api
  _start_web
  _start_celery

  local ok=0
  _wait_http "$API_URL/health" "api" || ok=1
  _wait_http "$PI_URL/health" "pi" || ok=1
  _wait_http "$WEB_URL/login" "web" || ok=1
  local demo_hint="create/login manually"
  if [[ "$ok" -eq 0 ]] && _seed_demo_user; then
    demo_hint="${DEMO_USER:-demo_elder} / ${DEMO_PASS:-demo1234}"
  fi

  if [[ "$ok" -ne 0 ]]; then
    echo "Start incomplete. Logs:" >&2
    echo "  $(_log_file api)" >&2
    echo "  $(_log_file web)" >&2
    echo "  $(_log_file pi)" >&2
    exit 1
  fi

  if ! cmd_doctor; then
    echo "Start incomplete: platform readiness did not pass." >&2
    exit 1
  fi
  _persist_profile
  echo "Started — open $WEB_URL/elder/companion  ($demo_hint)"
}

cmd_restart() {
  cmd_stop
  sleep 1
  cmd_start
}

usage() {
  echo "Usage: $0 {start|stop|restart|status|doctor}"
  exit 2
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  doctor) cmd_doctor ;;
  *) usage ;;
esac
