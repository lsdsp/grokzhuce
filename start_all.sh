#!/usr/bin/env bash
set -euo pipefail

THREADS=""
COUNT=""
MAX_ATTEMPTS=""
SOLVER_THREAD=""
SOLVER_RESULT_STORE_ARG=""
SOLVER_RESULT_DB_PATH_ARG=""
PROXY_HTTP=""
PROXY_SOCKS=""
NO_PROXY_MODE=0
GROK_FAILURE_PATTERNS=()

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
    --solver-result-store)
      SOLVER_RESULT_STORE_ARG="${2:-}"; shift 2 ;;
    --solver-result-db-path)
      SOLVER_RESULT_DB_PATH_ARG="${2:-}"; shift 2 ;;
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
  -s, --solver-thread <n>   solver 线程数（默认读取共享约定）
  --solver-result-store <k> solver 结果存储后端（memory/sqlite）
  --solver-result-db-path <p> SQLite 数据库路径
  --proxy-http <url>        HTTP/HTTPS 代理（默认读取共享约定）
  --proxy-socks <url>       SOCKS 代理（默认读取共享约定）
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

load_shared_defaults() {
  local key value
  # oneclick_shared.py defaults
  while IFS='=' read -r key value; do
    [[ -z "${key}" ]] && continue
    case "$key" in
      DEFAULT_THREADS) DEFAULT_THREADS="$value" ;;
      DEFAULT_COUNT) DEFAULT_COUNT="$value" ;;
      DEFAULT_SOLVER_THREAD) DEFAULT_SOLVER_THREAD="$value" ;;
      DEFAULT_PROXY_HTTP) DEFAULT_PROXY_HTTP="$value" ;;
      DEFAULT_PROXY_SOCKS) DEFAULT_PROXY_SOCKS="$value" ;;
      SOLVER_READY_TIMEOUT_SEC) SOLVER_READY_TIMEOUT_SEC="$value" ;;
      SOLVER_STOP_TIMEOUT_SEC) SOLVER_STOP_TIMEOUT_SEC="$value" ;;
      LOG_ROOT_DIR) LOG_ROOT_DIR="$value" ;;
      LOG_SOLVER_DIR) LOG_SOLVER_DIR="$value" ;;
      LOG_GROK_DIR) LOG_GROK_DIR="$value" ;;
      LOG_ONECLICK_DIR) LOG_ONECLICK_DIR="$value" ;;
      LOG_OTHERS_DIR) LOG_OTHERS_DIR="$value" ;;
    esac
  done < <("$PYTHON_BIN" "$project_root/oneclick_shared.py" defaults)
}

load_failure_patterns() {
  local line
  GROK_FAILURE_PATTERNS=()
  # oneclick_shared.py failure-patterns
  while IFS= read -r line; do
    [[ -n "$line" ]] && GROK_FAILURE_PATTERNS+=("$line")
  done < <("$PYTHON_BIN" "$project_root/oneclick_shared.py" failure-patterns)
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
  local timeout_sec="${SOLVER_STOP_TIMEOUT_SEC}"
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

write_diag() {
  echo "$1" | tee -a "$oneclick_log"
}

show_grok_failure_summary() {
  local log_path="$1"
  local summary_lines=()
  local pattern match

  if [[ ! -f "$log_path" ]]; then
    log "Unable to build failure summary: grok log not found."
    return 0
  fi

  for pattern in "${GROK_FAILURE_PATTERNS[@]}"; do
    match="$(grep -F "$pattern" "$log_path" 2>/dev/null | tail -n 1 || true)"
    if [[ -n "$match" ]]; then
      summary_lines+=("$match")
    fi
  done

  if (( ${#summary_lines[@]} > 0 )); then
    log "Failure summary from grok log:"
    printf '%s\n' "${summary_lines[@]}" | awk '!seen[$0]++' | head -n 6 | while IFS= read -r line; do
      write_diag "[diag] $line"
    done
    return 0
  fi

  log "Failure summary fallback: tail of grok log."
  tail -n 20 "$log_path" | while IFS= read -r line; do
    write_diag "[tail] $line"
  done
}

PYTHON_BIN="$(find_python)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "[-] Python not found. Please install Python 3.10+." >&2
  exit 1
fi

load_shared_defaults
load_failure_patterns

DEFAULT_THREADS="${DEFAULT_THREADS:-3}"
DEFAULT_COUNT="${DEFAULT_COUNT:-5}"
DEFAULT_SOLVER_THREAD="${DEFAULT_SOLVER_THREAD:-5}"
DEFAULT_PROXY_HTTP="${DEFAULT_PROXY_HTTP:-http://127.0.0.1:10808}"
DEFAULT_PROXY_SOCKS="${DEFAULT_PROXY_SOCKS:-socks5://127.0.0.1:10808}"
SOLVER_READY_TIMEOUT_SEC="${SOLVER_READY_TIMEOUT_SEC:-60}"
SOLVER_STOP_TIMEOUT_SEC="${SOLVER_STOP_TIMEOUT_SEC:-180}"
LOG_ROOT_DIR="${LOG_ROOT_DIR:-logs}"
LOG_SOLVER_DIR="${LOG_SOLVER_DIR:-logs/solver}"
LOG_GROK_DIR="${LOG_GROK_DIR:-logs/grok}"
LOG_ONECLICK_DIR="${LOG_ONECLICK_DIR:-logs/oneclick}"
LOG_OTHERS_DIR="${LOG_OTHERS_DIR:-logs/others}"

if [[ -z "$SOLVER_THREAD" ]]; then
  SOLVER_THREAD="$DEFAULT_SOLVER_THREAD"
fi
if [[ -z "$PROXY_HTTP" ]]; then
  PROXY_HTTP="$DEFAULT_PROXY_HTTP"
fi
if [[ -z "$PROXY_SOCKS" ]]; then
  PROXY_SOCKS="$DEFAULT_PROXY_SOCKS"
fi

mkdir -p "$LOG_SOLVER_DIR" "$LOG_GROK_DIR" "$LOG_ONECLICK_DIR" "$LOG_OTHERS_DIR"
ts="$(date +"%Y%m%d-%H%M%S")"
oneclick_log="${LOG_ONECLICK_DIR}/start_all.${ts}.log"
touch "$oneclick_log"

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

if [[ -n "$SOLVER_RESULT_STORE_ARG" ]] && [[ "$SOLVER_RESULT_STORE_ARG" != "memory" ]] && [[ "$SOLVER_RESULT_STORE_ARG" != "sqlite" ]]; then
  echo "[-] Invalid --solver-result-store value: $SOLVER_RESULT_STORE_ARG" >&2
  exit 1
fi

SOLVER_PID=""
cleanup() {
  stop_solver || true
  if [[ -n "${PREV_SOLVER_RESULT_STORE_SET:-}" ]]; then
    if [[ -n "${PREV_SOLVER_RESULT_STORE_VALUE}" ]]; then
      export SOLVER_RESULT_STORE="${PREV_SOLVER_RESULT_STORE_VALUE}"
    else
      unset SOLVER_RESULT_STORE || true
    fi
  fi
  if [[ -n "${PREV_SOLVER_RESULT_DB_PATH_SET:-}" ]]; then
    if [[ -n "${PREV_SOLVER_RESULT_DB_PATH_VALUE}" ]]; then
      export SOLVER_RESULT_DB_PATH="${PREV_SOLVER_RESULT_DB_PATH_VALUE}"
    else
      unset SOLVER_RESULT_DB_PATH || true
    fi
  fi
}
trap cleanup EXIT

if is_solver_ready; then
  log "Solver is already running at http://127.0.0.1:5072"
else
  if [[ "${SOLVER_RESULT_STORE+x}" == "x" ]]; then
    PREV_SOLVER_RESULT_STORE_SET=1
    PREV_SOLVER_RESULT_STORE_VALUE="${SOLVER_RESULT_STORE}"
  else
    PREV_SOLVER_RESULT_STORE_SET=1
    PREV_SOLVER_RESULT_STORE_VALUE=""
  fi
  if [[ "${SOLVER_RESULT_DB_PATH+x}" == "x" ]]; then
    PREV_SOLVER_RESULT_DB_PATH_SET=1
    PREV_SOLVER_RESULT_DB_PATH_VALUE="${SOLVER_RESULT_DB_PATH}"
  else
    PREV_SOLVER_RESULT_DB_PATH_SET=1
    PREV_SOLVER_RESULT_DB_PATH_VALUE=""
  fi
  if [[ -n "$SOLVER_RESULT_STORE_ARG" ]]; then
    export SOLVER_RESULT_STORE="$SOLVER_RESULT_STORE_ARG"
    log "Apply solver result store: ${SOLVER_RESULT_STORE}"
  fi
  if [[ -n "$SOLVER_RESULT_DB_PATH_ARG" ]]; then
    export SOLVER_RESULT_DB_PATH="$SOLVER_RESULT_DB_PATH_ARG"
    log "Apply solver result DB path: ${SOLVER_RESULT_DB_PATH}"
  fi
  solver_out="${LOG_SOLVER_DIR}/solver.oneclick.${ts}.out.log"
  solver_err="${LOG_SOLVER_DIR}/solver.oneclick.${ts}.err.log"
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
  for _ in $(seq 1 "$SOLVER_READY_TIMEOUT_SEC"); do
    sleep 1
    if is_solver_ready; then
      ready=1
      break
    fi
  done
  if (( ready == 0 )); then
    log "Solver not ready within ${SOLVER_READY_TIMEOUT_SEC} seconds; starting cleanup."
    stop_solver || true
    exit 1
  fi
  log "Solver is ready."
fi

if [[ -z "$THREADS" ]]; then
  THREADS="$(read_positive_int "请输入并发 threads" "$DEFAULT_THREADS")"
fi
if [[ -z "$COUNT" ]]; then
  COUNT="$(read_positive_int "请输入目标 count" "$DEFAULT_COUNT")"
fi
if ! is_positive_int "$THREADS"; then
  echo "[-] Invalid --threads value: $THREADS" >&2
  exit 1
fi
if ! is_positive_int "$COUNT"; then
  echo "[-] Invalid --count value: $COUNT" >&2
  exit 1
fi
if ! is_positive_int "$SOLVER_THREAD"; then
  echo "[-] Invalid --solver-thread value: $SOLVER_THREAD" >&2
  exit 1
fi
if [[ -n "$MAX_ATTEMPTS" ]] && ! is_positive_int "$MAX_ATTEMPTS"; then
  echo "[-] Invalid --max-attempts value: $MAX_ATTEMPTS" >&2
  exit 1
fi

grok_out="${LOG_GROK_DIR}/grok.oneclick.${ts}.out.log"
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

attempt_limit_hit=0
has_success=0
has_failure_pattern=0
if [[ -f "$grok_out" ]]; then
  if grep -Fq "[OK]" "$grok_out" || grep -Fq "注册成功:" "$grok_out"; then
    has_success=1
  fi
  if grep -Fq "ATTEMPT_LIMIT_REACHED" "$grok_out" || grep -Fq "已达到最大尝试上限" "$grok_out"; then
    attempt_limit_hit=1
  fi
  for hint in "${GROK_FAILURE_PATTERNS[@]}"; do
    if grep -Fq "$hint" "$grok_out"; then
      has_failure_pattern=1
      break
    fi
  done
fi

if (( exit_code != 0 || attempt_limit_hit == 1 || (has_success == 0 && has_failure_pattern == 1) )); then
  show_grok_failure_summary "$grok_out"
fi

exit "$exit_code"
