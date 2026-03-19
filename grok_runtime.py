import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


LOGGER = logging.getLogger("grok")
if not LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    LOGGER.addHandler(_handler)
LOGGER.setLevel(logging.INFO)


class ErrorType(str, Enum):
    NONE = "none"
    NETWORK = "network"
    TIMEOUT = "timeout"
    CAPTCHA = "captcha"
    PARSE = "parse"
    SIGNUP = "signup"
    DEPENDENCY = "dependency"
    POLICY = "policy"
    UNKNOWN = "unknown"


class StopReason(str, Enum):
    TARGET_REACHED = "target_reached"
    ATTEMPT_LIMIT = "attempt_limit"
    STAGE_FAILURE = "stage_failure"
    EXTERNAL_STOP = "external_stop"


@dataclass(frozen=True)
class AppConfig:
    thread_count: int
    target_count: int
    max_attempts: int
    keep_success_email: bool
    enable_nsfw: bool
    output_file: str
    proxies: Dict[str, str]
    metrics_path: str
    sso_output_mode: str = "plain"
    sso_encryption_passphrase: str = ""
    stage_failure_threshold: int = 20


@dataclass
class RuntimeContext:
    site_key: str
    action_id: Optional[str]
    state_tree: str


@dataclass
class StageResult:
    ok: bool
    stage: str
    error_type: ErrorType = ErrorType.NONE
    retryable: bool = False
    details: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    latency_ms: Optional[int] = None


@dataclass
class AttemptClaim:
    allowed: bool
    slot_no: int
    reason: Optional[StopReason] = None


class JsonlLogger:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def event(self, level: str, stage: str, message: str, **fields: Any):
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "stage": stage,
            "message": message,
            **fields,
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class StopPolicy:
    def __init__(self, target_count: int, max_attempts: int):
        self.target_count = max(1, int(target_count))
        self.max_attempts = max(1, int(max_attempts))
        self.success_count = 0
        self.attempt_count = 0
        self.stop_event = threading.Event()
        self.stop_reason: Optional[StopReason] = None
        self._lock = threading.Lock()

    def claim_attempt_slot(self) -> AttemptClaim:
        with self._lock:
            if self.stop_event.is_set():
                return AttemptClaim(False, self.attempt_count, self.stop_reason)
            if self.attempt_count >= self.max_attempts:
                self.stop_reason = StopReason.ATTEMPT_LIMIT
                self.stop_event.set()
                return AttemptClaim(False, self.attempt_count, self.stop_reason)
            self.attempt_count += 1
            return AttemptClaim(True, self.attempt_count, None)

    def mark_success(self) -> int:
        with self._lock:
            self.success_count += 1
            if self.success_count >= self.target_count:
                self.stop_reason = StopReason.TARGET_REACHED
                self.stop_event.set()
            return self.success_count

    def stop(self, reason: StopReason):
        with self._lock:
            if self.stop_reason is None:
                self.stop_reason = reason
            self.stop_event.set()

    def should_stop(self) -> bool:
        return self.stop_event.is_set()
