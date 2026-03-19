import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from grok_config import DEFAULT_SITE_KEY, DEFAULT_STATE_TREE
from grok_runtime import StopReason


@dataclass
class CompatibilityState:
    config: dict = field(
        default_factory=lambda: {
            "site_key": DEFAULT_SITE_KEY,
            "action_id": None,
            "state_tree": DEFAULT_STATE_TREE,
        }
    )
    success_count: int = 0
    attempt_count: int = 0
    start_time: float = field(default_factory=time.time)
    target_count: int = 100
    max_attempts: int = 0
    stop_event: threading.Event = field(default_factory=threading.Event)
    attempt_limit_reached: threading.Event = field(default_factory=threading.Event)
    output_file: Optional[str] = None


state = CompatibilityState()


def reset_state():
    state.success_count = 0
    state.attempt_count = 0
    state.start_time = time.time()
    state.stop_event.clear()
    state.attempt_limit_reached.clear()


def sync_main_state(*, target_count: int, max_attempts: int, output_file: str):
    state.target_count = target_count
    state.max_attempts = max_attempts
    state.output_file = output_file


def sync_runner_state(runner):
    state.config.update(
        {
            "site_key": runner.runtime.site_key,
            "state_tree": runner.runtime.state_tree,
            "action_id": runner.runtime.action_id,
        }
    )
    state.success_count = runner.stop.success_count
    state.attempt_count = runner.stop.attempt_count
    state.attempt_limit_reached.clear()
    state.stop_event.clear()
    if runner.stop.stop_reason == StopReason.ATTEMPT_LIMIT:
        state.attempt_limit_reached.set()
        state.stop_event.set()


__all__ = [
    "CompatibilityState",
    "reset_state",
    "state",
    "sync_main_state",
    "sync_runner_state",
]
