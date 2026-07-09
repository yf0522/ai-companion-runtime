#!/usr/bin/env bash
# Local demo stack: API :8001, Web :3000, Pi sidecar :8787
# Usage: ./scripts/local_stack.sh {start|stop|restart|status}
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="${LOCAL_STACK_RUN_DIR:-$ROOT/.local-stack}"
API_PORT="${API_PORT:-8001}"
WEB_PORT="${WEB_PORT:-3000}"
PI_PORT="${PI_PORT:-8787}"
API_HOST="127.0.0.1"
WEB_HOST="127.0.0.1"
PI_HOST="127.0.0.1"

API_URL="http://${API_HOST}:${API_PORT}"
WEB_URL="http://${WEB_HOST}:${WEB_PORT}"
PI_URL="http://${PI_HOST}:${PI_PORT}"
WS_URL="ws://${API_HOST}:${API_PORT}/ws/chat"
BRIDGE_URL="${TOOL_BRIDGE_URL:-${API_URL}/api}"

mkdir -p "$RUN_DIR"

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

_wait_http() {
  local url="$1"
  local name="$2"
  local tries="${3:-40}"
  local i code
  for ((i = 1; i <= tries; i++)); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 1 "$url" 2>/dev/null || echo 000)"
    if [[ "$code" =~ ^[23] ]]; then
      echo "  ok  $name ($code) $url"
      return 0
    fi
    sleep 0.5
  done
  echo "  FAIL $name — last HTTP $code — see $(_log_file "$(echo "$name" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')")" >&2
  return 1
}

_load_env() {
  set -a
  [[ -f "$ROOT/.env" ]] && . "$ROOT/.env"
  [[ -f "$ROOT/apps/api/.env" ]] && . "$ROOT/apps/api/.env"
  set +a
  export ENABLE_PI_RUNTIME="${ENABLE_PI_RUNTIME:-1}"
  export PI_SIDECAR_URL="${PI_SIDECAR_URL:-$PI_URL}"
  export TOOL_BRIDGE_URL="$BRIDGE_URL"
  export NEXT_PUBLIC_API_URL="$API_URL"
  export NEXT_PUBLIC_WS_URL="$WS_URL"
}

cmd_stop() {
  echo "Stopping local stack..."
  if command -v tmux >/dev/null 2>&1; then
    for s in companion-web companion-api companion-pi; do
      tmux has-session -t "=$s" 2>/dev/null && tmux kill-session -t "=$s" 2>/dev/null || true
    done
  fi
  _kill_port "$WEB_PORT"
  _kill_port "$API_PORT"
  _kill_port "$PI_PORT"
  rm -f "$(_pid_file pi)" "$(_pid_file api)" "$(_pid_file web)"
  echo "Stopped."
}

cmd_status() {
  echo "Local stack status (SHA $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo '?'))"
  for pair in "web:$WEB_PORT:$WEB_URL/chat" "api:$API_PORT:$API_URL/health" "pi:$PI_PORT:$PI_URL/health"; do
    IFS=: read -r name port url <<<"$pair"
    if _is_listening "$port"; then
      code="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 1 "$url" 2>/dev/null || echo 000)"
      echo "  UP   $name :$port HTTP $code"
    else
      echo "  DOWN $name :$port"
    fi
  done
}

_have_tmux() { command -v tmux >/dev/null 2>&1; }

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
  local log
  log="$(_log_file pi)"
  if _have_tmux; then
    _tmux_start companion-pi "$ROOT/apps/pi-sidecar" \
      "env TOOL_BRIDGE_URL='$TOOL_BRIDGE_URL' TOOL_BRIDGE_TOKEN='${TOOL_BRIDGE_TOKEN:-}' node server.mjs 2>&1 | tee '$log'"
  else
    (
      cd "$ROOT/apps/pi-sidecar"
      # double-fork so we survive parent shell death
      (setsid env TOOL_BRIDGE_URL="$TOOL_BRIDGE_URL" TOOL_BRIDGE_TOKEN="${TOOL_BRIDGE_TOKEN:-}" \
        node server.mjs >"$log" 2>&1 &)
      sleep 0.2
      lsof -tiTCP:"$PI_PORT" -sTCP:LISTEN >"$(_pid_file pi)" 2>/dev/null || true
    )
  fi
}

_start_api() {
  local log
  log="$(_log_file api)"
  if _have_tmux; then
    _tmux_start companion-api "$ROOT/apps/api" \
      "env ENABLE_PI_RUNTIME='$ENABLE_PI_RUNTIME' PI_SIDECAR_URL='$PI_SIDECAR_URL' TOOL_BRIDGE_URL='$TOOL_BRIDGE_URL' PYTHONPATH=. uv run uvicorn app.main:app --host '$API_HOST' --port '$API_PORT' 2>&1 | tee '$log'"
  else
    (
      cd "$ROOT/apps/api"
      (setsid env ENABLE_PI_RUNTIME="$ENABLE_PI_RUNTIME" PI_SIDECAR_URL="$PI_SIDECAR_URL" \
        TOOL_BRIDGE_URL="$TOOL_BRIDGE_URL" PYTHONPATH=. \
        uv run uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" >"$log" 2>&1 &)
      sleep 0.2
      lsof -tiTCP:"$API_PORT" -sTCP:LISTEN >"$(_pid_file api)" 2>/dev/null || true
    )
  fi
}

_start_web() {
  local log
  log="$(_log_file web)"
  if _have_tmux; then
    _tmux_start companion-web "$ROOT/apps/web" \
      "env NEXT_PUBLIC_API_URL='$NEXT_PUBLIC_API_URL' NEXT_PUBLIC_WS_URL='$NEXT_PUBLIC_WS_URL' npm run dev -- -p '$WEB_PORT' -H '$WEB_HOST' 2>&1 | tee '$log'"
  else
    (
      cd "$ROOT/apps/web"
      (setsid env NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" NEXT_PUBLIC_WS_URL="$NEXT_PUBLIC_WS_URL" \
        npm run dev -- -p "$WEB_PORT" -H "$WEB_HOST" >"$log" 2>&1 &)
      sleep 0.2
      lsof -tiTCP:"$WEB_PORT" -sTCP:LISTEN >"$(_pid_file web)" 2>/dev/null || true
    )
  fi
}

cmd_start() {
  _load_env
  echo "Starting local stack in $ROOT"
  echo "  API  $API_URL"
  echo "  Web  $WEB_URL/chat"
  echo "  Pi   $PI_URL  bridge=$TOOL_BRIDGE_URL"
  echo "  logs $RUN_DIR/*.log"

  if _is_listening "$API_PORT" || _is_listening "$WEB_PORT" || _is_listening "$PI_PORT"; then
    echo "Ports in use — stopping first..."
    cmd_stop
    sleep 1
  fi

  _start_pi
  _start_api
  _start_web

  local ok=0
  _wait_http "$API_URL/health" "api" || ok=1
  _wait_http "$PI_URL/health" "pi" || ok=1
  _wait_http "$WEB_URL/chat" "web" || ok=1

  if [[ "$ok" -ne 0 ]]; then
    echo "Start incomplete. Logs:" >&2
    echo "  $(_log_file api)" >&2
    echo "  $(_log_file web)" >&2
    echo "  $(_log_file pi)" >&2
    exit 1
  fi

  echo "READY — open $WEB_URL/chat  (demo_elder / demo1234)"
}

cmd_restart() {
  cmd_stop
  sleep 1
  cmd_start
}

usage() {
  echo "Usage: $0 {start|stop|restart|status}"
  exit 2
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  *) usage ;;
esac
