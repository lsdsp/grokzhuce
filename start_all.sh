#!/usr/bin/env bash
set -euo pipefail

THREADS=""
COUNT=""
MAX_ATTEMPTS=""
SOLVER_THREAD=5
PROXY_HTTP="http://127.0.0.1:10808"
PROXY_SOCKS="socks5://127.0.0.1:10808"
NO_PROXY_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--threads)
      THREADS="${2:-}"; shift 2 ;;
    -c|--count)
      COUNT="${2:-}"; shift 2 ;;
    -m|--max-attempts)
      MAX_ATTEMPTS="${2:-}"; shift 2 ;;
    -s|--solver-thread)
      SOLVER_THREAD="${2:-}"; shift 2 ;;
    --proxy-http)
      PROXY_HTTP="${2:-}"; shift 2 ;;
    --proxy-socks)
      PROXY_SOCKS="${2:-}"; shift 2 ;;
    --no-proxy)
      NO_PROXY_MODE=1; shift ;;
    -h|--help)
      cat <<'USAGE'
Usage:
  ./start_all.sh [options]

Options:
  -t, --threads <n>         grok 并发线程数
  -c, --count <n>           目标注册数量
  -m, --max-attempts <n>    最大尝试次数（可选）
  -s, --solver-thread <n>   solver 线程数（默认 5）
  --proxy-http <url>        HTTP/HTTPS 代理（默认 http://127.0.0.1:10808）
  --proxy-socks <url>       SOCKS 代理（默认 socks5://127.0.0.1:10808）
  --no-proxy                禁用代理
USAGE
      exit 0 ;;
    *)
      echo "[!] Unknown arg: $1" >&2
      exit 1 ;;
  esac
done

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_root"

mkdir -p logs/solver logs/grok logs/oneclick logs/others
ts="$(date +"%Y%m%d-%H%M%S")"
oneclick_log="logs/oneclick/start_all.${ts}.log"
touch "$oneclick_log"

log() {
  local line
  line="[$(date +"%Y-%m-%d %H:%M:%S")] [*] $*"
  echo "$line" | tee -a "$oneclick_log"
}

is_positive_int() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

read_positive_int() {
  local prompt="$1"
  local default_value="$2"
  local input=""
  while true; do
    read -r -p "${prompt} (默认 ${default_value}): " input
    input="${input:-$default_value}"
    if is_positive_int "$input"; then
      echo "$input"
      return 0
    fi
    echo "[!] 请输入正整数。"
  done
}

find_python() {
  if [[ -x ".venv/bin/python" ]]; then
    echo ".venv/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return 0
  fi
  echo ""
}

is_solver_ready() {
  "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import socket, sys
s = socket.socket()
s.settimeout(0.5)
try:
    s.connect(("127.0.0.1", 5072))
except Exception:
    sys.exit(1)
finally:
    s.close()
sys.exit(0)
PY
}

stop_solver() {
  local timeout_sec=180
  local start_epoch
  start_epoch="$(date +%s)"
  log "Stopping solver (timeout ${timeout_sec}s)..."

  while is_solver_ready; do
    if [[ -n "${SOLVER_PID:-}" ]] && kill -0 "$SOLVER_PID" >/dev/null 2>&1; then
      kill "$SOLVER_PID" >/dev/null 2>&1 || true
    else
      pkill -f "api_solver.py" >/dev/null 2>&1 || true
    fi
    sleep 2
    if (( "$(date +%s)" - start_epoch >= timeout_sec )); then
      break
    fi
  done

  if is_solver_ready; then
    log "Timeout reached, force stopping solver..."
    if [[ -n "${SOLVER_PID:-}" ]]; then
      kill -9 "$SOLVER_PID" >/dev/null 2>&1 || true
    fi
    pkill -9 -f "api_solver.py" >/dev/null 2>&1 || true
    sleep 2
  fi

  if is_solver_ready; then
    log "Solver may still be running."
    return 1
  fi
  log "Solver stopped."
  return 0
}

PYTHON_BIN="$(find_python)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "[-] Python not found. Please install Python 3.10+." >&2
  exit 1
fi

if (( NO_PROXY_MODE == 1 )); then
  log "Proxy disabled by --no-proxy."
  unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY || true
else
  log "Applying local proxy: ${PROXY_HTTP} / ${PROXY_SOCKS}"
  export http_proxy="$PROXY_HTTP"
  export https_proxy="$PROXY_HTTP"
  export all_proxy="$PROXY_SOCKS"
  export HTTP_PROXY="$PROXY_HTTP"
  export HTTPS_PROXY="$PROXY_HTTP"
  export ALL_PROXY="$PROXY_SOCKS"
fi

SOLVER_PID=""
cleanup() {
  stop_solver || true
}
trap cleanup EXIT

if is_solver_ready; then
  log "Solver is already running at http://127.0.0.1:5072"
else
  solver_out="logs/solver/solver.oneclick.${ts}.out.log"
  solver_err="logs/solver/solver.oneclick.${ts}.err.log"
  solver_args=(api_solver.py --browser_type camoufox --thread "$SOLVER_THREAD" --debug)
  if (( NO_PROXY_MODE == 0 )); then
    solver_args+=(--proxy)
  fi
  log "Starting solver (threads=${SOLVER_THREAD})..."
  "$PYTHON_BIN" "${solver_args[@]}" >"$solver_out" 2>"$solver_err" &
  SOLVER_PID="$!"
  log "Solver PID: ${SOLVER_PID}"
  log "Solver logs: ${solver_out} / ${solver_err}"

  ready=0
  for _ in $(seq 1 60); do
    sleep 1
    if is_solver_ready; then
      ready=1
      break
    fi
  done
  if (( ready == 0 )); then
    log "Solver not ready within 60 seconds."
    exit 1
  fi
  log "Solver is ready."
fi

if [[ -z "$THREADS" ]]; then
  THREADS="$(read_positive_int "请输入并发 threads" "3")"
fi
if [[ -z "$COUNT" ]]; then
  COUNT="$(read_positive_int "请输入目标 count" "5")"
fi
if ! is_positive_int "$THREADS"; then
  echo "[-] Invalid --threads value: $THREADS" >&2
  exit 1
fi
if ! is_positive_int "$COUNT"; then
  echo "[-] Invalid --count value: $COUNT" >&2
  exit 1
fi
if [[ -n "$MAX_ATTEMPTS" ]] && ! is_positive_int "$MAX_ATTEMPTS"; then
  echo "[-] Invalid --max-attempts value: $MAX_ATTEMPTS" >&2
  exit 1
fi

grok_out="logs/grok/grok.oneclick.${ts}.out.log"
grok_args=(-u grok.py --threads "$THREADS" --count "$COUNT")
if [[ -n "$MAX_ATTEMPTS" ]]; then
  grok_args+=(--max-attempts "$MAX_ATTEMPTS")
fi
log "Starting grok with --threads ${THREADS} --count ${COUNT}"
log "Grok log: ${grok_out}"
if [[ -n "$MAX_ATTEMPTS" ]]; then
  log "Apply max attempts: ${MAX_ATTEMPTS}"
fi

set +e
"$PYTHON_BIN" "${grok_args[@]}" 2>&1 | tee "$grok_out"
exit_code="${PIPESTATUS[0]}"
set -e
log "grok.py exited with code ${exit_code}"
exit "$exit_code"
