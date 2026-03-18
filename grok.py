import argparse
import os
import threading
import time

from grok_config import (
    DEFAULT_SITE_KEY,
    DEFAULT_SITE_URL,
    DEFAULT_STATE_TREE,
    ENABLE_NSFW,
    KEEP_SUCCESS_EMAIL,
    PROXIES,
    build_default_runtime_context,
    build_main_config,
    compute_effective_max_attempts,
    read_bool_env,
    should_delete_email_after_registration,
)
from grok_protocol import (
    CHROME_PROFILES,
    EMAIL_CODE_POLL_ATTEMPTS_PER_ROUND,
    EMAIL_CODE_REQUEST_ROUNDS,
    MAX_EMAIL_CODE_CYCLES_PER_EMAIL,
    SIGNUP_RETRY_PER_CODE,
    compact_text,
    encode_grpc_message,
    encode_grpc_message_verify,
    generate_random_name,
    generate_random_string,
    get_random_chrome_profile,
    mask_email,
    request_and_wait_for_email_code as _request_and_wait_for_email_code,
    send_email_code_grpc as _send_email_code_grpc,
    verify_email_code_grpc as _verify_email_code_grpc,
)
from grok_registration import GrokRunner
from grok_runtime import (
    LOGGER,
    AppConfig,
    AttemptClaim,
    ErrorType,
    JsonlLogger,
    RuntimeContext,
    StageResult,
    StopPolicy,
    StopReason,
)


site_url = DEFAULT_SITE_URL
config = {
    "site_key": DEFAULT_SITE_KEY,
    "action_id": None,
    "state_tree": DEFAULT_STATE_TREE,
}

# compatibility globals; runtime logic now lives in StopPolicy/GrokRunner
post_lock = threading.Lock()
file_lock = threading.Lock()
attempt_lock = threading.Lock()
success_count = 0
attempt_count = 0
start_time = time.time()
target_count = 100
max_attempts = 0
stop_event = threading.Event()
attempt_limit_reached = threading.Event()
output_file = None


def reset_runtime_state():
    global success_count, attempt_count, start_time
    success_count = 0
    attempt_count = 0
    start_time = time.time()
    stop_event.clear()
    attempt_limit_reached.clear()


def register_single_thread():
    raise RuntimeError("register_single_thread 已弃用，请通过 main()/GrokRunner.run() 启动。")


def send_email_code_grpc(session, email, **kwargs):
    return _send_email_code_grpc(session, email, **kwargs)


def request_and_wait_for_email_code(session, email_service, email, **kwargs):
    kwargs.setdefault("send_func", send_email_code_grpc)
    return _request_and_wait_for_email_code(session, email_service, email, **kwargs)


def verify_email_code_grpc(session, email, code, **kwargs):
    return _verify_email_code_grpc(session, email, code, **kwargs)


def _read_int_with_default(prompt: str, default_value: int) -> int:
    try:
        return int(input(prompt).strip() or default_value)
    except Exception:
        return default_value


def main(thread_count=None, total_count=None, max_attempts_arg=None, metrics_file=None):
    print("=" * 60 + "\nGrok 注册机\n" + "=" * 60)
    threads = int(thread_count) if thread_count is not None else _read_int_with_default("\n并发数 (默认8): ", 8)
    total = int(total_count) if total_count is not None else _read_int_with_default("注册数量 (默认100): ", 100)

    threads = max(1, threads)
    total = max(1, total)
    cfg = build_main_config(
        thread_count=threads,
        total_count=total,
        max_attempts_arg=max_attempts_arg,
        metrics_file=metrics_file,
        keep_success_email=KEEP_SUCCESS_EMAIL,
        enable_nsfw=ENABLE_NSFW,
        proxies=PROXIES,
    )

    os.makedirs("keys", exist_ok=True)
    os.makedirs("logs/grok", exist_ok=True)

    global target_count, max_attempts, output_file, success_count, attempt_count
    target_count = total
    max_attempts = cfg.max_attempts
    output_file = cfg.output_file
    reset_runtime_state()

    print(f"[*] 启动 {threads} 个线程，目标 {total} 个")
    print(f"[*] 最大尝试上限: {cfg.max_attempts}")
    if max_attempts_arg is None:
        print(f"[*] 未指定 --max-attempts，自动使用 {cfg.max_attempts}。如网络不稳定可手动调整（例如 --max-attempts {total * 4}）。")

    runtime = build_default_runtime_context()
    runner = GrokRunner(cfg, runtime=runtime, site_url=site_url)
    code = runner.run()

    config.update(
        {
            "site_key": runner.runtime.site_key,
            "state_tree": runner.runtime.state_tree,
            "action_id": runner.runtime.action_id,
        }
    )

    success_count = runner.stop.success_count
    attempt_count = runner.stop.attempt_count
    if runner.stop.stop_reason == StopReason.ATTEMPT_LIMIT:
        attempt_limit_reached.set()
        stop_event.set()
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grok batch registration")
    parser.add_argument("--threads", type=int, default=None, help="并发数")
    parser.add_argument("--count", type=int, default=None, help="注册数量")
    parser.add_argument("--max-attempts", type=int, default=None, help="最大尝试次数（默认按 count 自动计算）")
    parser.add_argument("--metrics-file", type=str, default=None, help="结构化指标日志输出路径（JSONL）")
    args = parser.parse_args()
    raise SystemExit(
        main(
            thread_count=args.threads,
            total_count=args.count,
            max_attempts_arg=args.max_attempts,
            metrics_file=args.metrics_file,
        )
    )
