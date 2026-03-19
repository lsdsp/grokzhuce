import unittest
from datetime import datetime
from unittest.mock import patch

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
        self.assertEqual(cfg.sso_output_mode, "plain")

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

    def test_build_main_config_reads_sso_output_mode_from_env(self):
        from grok_config import build_main_config

        with patch.dict("os.environ", {"SSO_OUTPUT_MODE": "masked"}, clear=False):
            cfg = build_main_config(
                thread_count=1,
                total_count=2,
                max_attempts_arg=4,
                now=datetime(2026, 3, 18, 8, 0, 0),
                proxies={},
            )

        self.assertEqual(cfg.sso_output_mode, "masked")

    def test_build_main_config_accepts_encrypted_mode_with_passphrase(self):
        from grok_config import build_main_config

        with patch.dict(
            "os.environ",
            {
                "SSO_OUTPUT_MODE": "encrypted",
                "SSO_ENCRYPTION_PASSPHRASE": "correct horse battery staple",
            },
            clear=False,
        ):
            cfg = build_main_config(
                thread_count=1,
                total_count=2,
                max_attempts_arg=4,
                now=datetime(2026, 3, 18, 8, 0, 0),
                proxies={},
            )

        self.assertEqual(cfg.sso_output_mode, "encrypted")

    def test_build_main_config_rejects_encrypted_mode_without_passphrase(self):
        from grok_config import build_main_config

        with patch.dict(
            "os.environ",
            {
                "SSO_OUTPUT_MODE": "encrypted",
                "SSO_ENCRYPTION_PASSPHRASE": "",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "SSO_ENCRYPTION_PASSPHRASE"):
                build_main_config(
                    thread_count=1,
                    total_count=2,
                    max_attempts_arg=4,
                    now=datetime(2026, 3, 18, 8, 0, 0),
                    proxies={},
                )

    def test_build_main_config_falls_back_to_plain_for_invalid_output_mode(self):
        from grok_config import build_main_config

        with patch.dict("os.environ", {"SSO_OUTPUT_MODE": "unexpected"}, clear=False):
            cfg = build_main_config(
                thread_count=1,
                total_count=2,
                max_attempts_arg=4,
                now=datetime(2026, 3, 18, 8, 0, 0),
                proxies={},
            )

        self.assertEqual(cfg.sso_output_mode, "plain")


if __name__ == "__main__":
    unittest.main()
