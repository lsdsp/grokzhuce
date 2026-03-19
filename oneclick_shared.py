from __future__ import annotations

import sys
from typing import Dict, List


DEFAULTS: Dict[str, str] = {
    "DEFAULT_THREADS": "3",
    "DEFAULT_COUNT": "5",
    "DEFAULT_SOLVER_THREAD": "5",
    "DEFAULT_SMOKE_SOLVER_THREAD": "2",
    "DEFAULT_PROXY_HTTP": "http://127.0.0.1:10808",
    "DEFAULT_PROXY_SOCKS": "socks5://127.0.0.1:10808",
    "SOLVER_READY_TIMEOUT_SEC": "60",
    "SOLVER_STOP_TIMEOUT_SEC": "180",
    "SMOKE_READY_TIMEOUT_SEC": "90",
    "LOG_ROOT_DIR": "logs",
    "LOG_SOLVER_DIR": "logs/solver",
    "LOG_GROK_DIR": "logs/grok",
    "LOG_ONECLICK_DIR": "logs/oneclick",
    "LOG_OTHERS_DIR": "logs/others",
}


FAILURE_PATTERNS: List[str] = [
    "ATTEMPT_LIMIT_REACHED",
    "已达到最大尝试上限",
    "初始化扫描失败",
    "未找到 Action ID",
    "服务初始化失败",
    "Traceback",
    "ModuleNotFoundError",
    "TLS connect error",
    "Connection timed out",
    "Resolving timed out",
    "SSLError",
    "Timeout",
]


def get_defaults() -> Dict[str, str]:
    return dict(DEFAULTS)


def get_failure_patterns() -> List[str]:
    return list(FAILURE_PATTERNS)


def main(argv: List[str]) -> int:
    if len(argv) != 2 or argv[1] not in {"defaults", "failure-patterns"}:
        print("usage: python oneclick_shared.py [defaults|failure-patterns]", file=sys.stderr)
        return 1

    if argv[1] == "defaults":
        for key, value in DEFAULTS.items():
            print(f"{key}={value}")
        return 0

    for item in FAILURE_PATTERNS:
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
