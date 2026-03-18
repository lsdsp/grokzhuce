import unittest
from datetime import datetime

from grok_runtime import AppConfig


class GrokConfigTests(unittest.TestCase):
    def test_build_main_config_uses_explicit_metrics_path(self):
        from grok_config import build_main_config

        now = datetime(2026, 3, 18, 12, 34, 56)
        cfg = build_main_config(
            thread_count=3,
            total_count=5,
            max_attempts_arg=12,
            metrics_file="logs/custom.jsonl",
            now=now,
            keep_success_email=True,
            enable_nsfw=False,
            proxies={"https": "http://127.0.0.1:10808"},
        )

        self.assertIsInstance(cfg, AppConfig)
        self.assertEqual(cfg.thread_count, 3)
        self.assertEqual(cfg.target_count, 5)
        self.assertEqual(cfg.max_attempts, 12)
        self.assertTrue(cfg.keep_success_email)
        self.assertFalse(cfg.enable_nsfw)
        self.assertEqual(cfg.output_file, "keys/grok_20260318_123456_5.txt")
        self.assertEqual(cfg.metrics_path, "logs/custom.jsonl")
        self.assertEqual(cfg.proxies, {"https": "http://127.0.0.1:10808"})

    def test_build_main_config_computes_default_attempt_budget(self):
        from grok_config import build_main_config

        cfg = build_main_config(
            thread_count=1,
            total_count=4,
            max_attempts_arg=None,
            metrics_file=None,
            now=datetime(2026, 3, 18, 8, 0, 0),
            keep_success_email=False,
            enable_nsfw=True,
            proxies={},
        )

        self.assertEqual(cfg.max_attempts, 16)
        self.assertEqual(cfg.metrics_path, "logs/grok/metrics.20260318_080000.jsonl")


if __name__ == "__main__":
    unittest.main()
