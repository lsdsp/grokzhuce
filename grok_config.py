from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv

from g.proxy_utils import build_requests_proxies
from grok_runtime import AppConfig, RuntimeContext


load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

DEFAULT_SITE_URL = "https://accounts.x.ai"
DEFAULT_IMPERSONATE = "chrome120"
DEFAULT_SITE_KEY = "0x4AAAAAAAhr9JGVDZbrZOo0"
DEFAULT_STATE_TREE = (
    "%5B%22%22%2C%7B%22children%22%3A%5B%22(app)%22%2C%7B%22children%22%3A%5B%22(auth)%22"
    "%2C%7B%22children%22%3A%5B%22sign-up%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D"
    "%2C%22%2Fsign-up%22%2C%22refresh%22%5D%7D%5D%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%5D%7D"
    "%2Cnull%2Cnull%2Ctrue%5D"
)


def read_bool_env(name: str, default: bool) -> bool:
    import os

    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


KEEP_SUCCESS_EMAIL = read_bool_env("KEEP_SUCCESS_EMAIL", False)
ENABLE_NSFW = read_bool_env("ENABLE_NSFW", True)
PROXIES = build_requests_proxies(preferred_keys=("GROK_PROXY_URL",))


def should_delete_email_after_registration(registration_succeeded: bool, keep_success_email: Optional[bool] = None) -> bool:
    if keep_success_email is None:
        keep_success_email = KEEP_SUCCESS_EMAIL
    return (not registration_succeeded) or (not keep_success_email)


def compute_effective_max_attempts(target: int, max_attempts_arg=None) -> int:
    target = max(1, int(target))
    if max_attempts_arg is None:
        return max(target * 4, target + 10)
    try:
        provided = int(max_attempts_arg)
    except Exception:
        provided = 1
    return max(1, provided)


def build_default_runtime_context() -> RuntimeContext:
    return RuntimeContext(DEFAULT_SITE_KEY, None, DEFAULT_STATE_TREE)


def build_main_config(
    *,
    thread_count: int,
    total_count: int,
    max_attempts_arg=None,
    metrics_file: Optional[str] = None,
    now: Optional[datetime] = None,
    keep_success_email: Optional[bool] = None,
    enable_nsfw: Optional[bool] = None,
    proxies: Optional[Dict[str, str]] = None,
) -> AppConfig:
    current = now or datetime.now()
    timestamp = current.strftime("%Y%m%d_%H%M%S")
    output_file = f"keys/grok_{timestamp}_{total_count}.txt"
    metrics_path = metrics_file or f"logs/grok/metrics.{timestamp}.jsonl"
    return AppConfig(
        thread_count=max(1, int(thread_count)),
        target_count=max(1, int(total_count)),
        max_attempts=compute_effective_max_attempts(total_count, max_attempts_arg),
        keep_success_email=KEEP_SUCCESS_EMAIL if keep_success_email is None else bool(keep_success_email),
        enable_nsfw=ENABLE_NSFW if enable_nsfw is None else bool(enable_nsfw),
        output_file=output_file,
        proxies=dict(PROXIES if proxies is None else proxies),
        metrics_path=metrics_path,
    )
