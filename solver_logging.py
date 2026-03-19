import logging
import os
import sys
import time

from grok_runtime import JsonlLogger


COLORS = {
    "MAGENTA": "\033[35m",
    "BLUE": "\033[34m",
    "GREEN": "\033[32m",
    "YELLOW": "\033[33m",
    "RED": "\033[31m",
    "RESET": "\033[0m",
}


class CustomLogger(logging.Logger):
    @staticmethod
    def format_message(level, color, message):
        timestamp = time.strftime("%H:%M:%S")
        return f"[{timestamp}] [{COLORS.get(color)}{level}{COLORS.get('RESET')}] -> {message}"

    def debug(self, message, *args, **kwargs):
        super().debug(self.format_message("DEBUG", "MAGENTA", message), *args, **kwargs)

    def info(self, message, *args, **kwargs):
        super().info(self.format_message("INFO", "BLUE", message), *args, **kwargs)

    def success(self, message, *args, **kwargs):
        super().info(self.format_message("SUCCESS", "GREEN", message), *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        super().warning(self.format_message("WARNING", "YELLOW", message), *args, **kwargs)

    def error(self, message, *args, **kwargs):
        super().error(self.format_message("ERROR", "RED", message), *args, **kwargs)


def get_solver_logger(name: str = "TurnstileAPIServer") -> CustomLogger:
    logging.setLoggerClass(CustomLogger)
    logger = logging.getLogger(name)  # type: ignore[assignment]
    logger.setLevel(logging.DEBUG)
    if not any(isinstance(handler, logging.StreamHandler) and getattr(handler, "stream", None) is sys.stdout for handler in logger.handlers):
        logger.addHandler(logging.StreamHandler(sys.stdout))
    return logger  # type: ignore[return-value]


def get_solver_event_logger(path: str | None = None) -> JsonlLogger:
    metrics_path = path or os.getenv("SOLVER_METRICS_PATH", "logs/solver/metrics.jsonl").strip() or "logs/solver/metrics.jsonl"
    return JsonlLogger(metrics_path)
