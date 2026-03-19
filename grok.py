import argparse
import os
import sys
import types

from grok_env import load_project_env

load_project_env()

import grok_compat
from grok_config import (
    DEFAULT_SITE_URL,
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
    request_and_wait_for_email_code as _request_and_wait_for_email_code,
    send_email_code_grpc as _send_email_code_grpc,
    verify_email_code_grpc as _verify_email_code_grpc,
)
from grok_registration import GrokRunner
from grok_runtime import (
    JsonlLogger,
    StopPolicy,
    StopReason,
)

__all__ = [
    "JsonlLogger",
    "StopPolicy",
    "StopReason",
    "attempt_count",
    "attempt_limit_reached",
    "compute_effective_max_attempts",
    "config",
    "main",
    "max_attempts",
    "output_file",
    "read_bool_env",
    "request_and_wait_for_email_code",
    "reset_runtime_state",
    "send_email_code_grpc",
    "should_delete_email_after_registration",
    "site_url",
    "stop_event",
    "success_count",
    "target_count",
    "verify_email_code_grpc",
]


site_url = DEFAULT_SITE_URL
_COMPAT_ATTRS = {
    "config",
    "success_count",
    "attempt_count",
    "target_count",
    "max_attempts",
    "stop_event",
    "attempt_limit_reached",
    "output_file",
}


def reset_runtime_state():
    grok_compat.reset_state()


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


def _sync_runner_compat_state(runner):
    grok_compat.sync_runner_state(runner)


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

    grok_compat.sync_main_state(target_count=total, max_attempts=cfg.max_attempts, output_file=cfg.output_file)
    reset_runtime_state()

    print(f"[*] 启动 {threads} 个线程，目标 {total} 个")
    print(f"[*] 最大尝试上限: {cfg.max_attempts}")
    if max_attempts_arg is None:
        print(f"[*] 未指定 --max-attempts，自动使用 {cfg.max_attempts}。如网络不稳定可手动调整（例如 --max-attempts {total * 4}）。")

    runtime = build_default_runtime_context()
    runner = GrokRunner(cfg, runtime=runtime, site_url=site_url)
    code = runner.run()
    _sync_runner_compat_state(runner)
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


class _GrokModule(types.ModuleType):
    def __getattr__(self, name):
        if name in _COMPAT_ATTRS:
            return getattr(grok_compat.state, name)
        return super().__getattribute__(name)

    def __setattr__(self, name, value):
        if name in _COMPAT_ATTRS:
            setattr(grok_compat.state, name, value)
            return
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _GrokModule
