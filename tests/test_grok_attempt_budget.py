import unittest
from types import SimpleNamespace
from unittest.mock import patch

import grok
from grok_runtime import AppConfig, RuntimeContext, StopReason


class GrokAttemptBudgetTests(unittest.TestCase):
    def setUp(self):
        grok.reset_runtime_state()
        grok.max_attempts = 0

    def tearDown(self):
        grok.reset_runtime_state()
        grok.max_attempts = 0

    def test_compute_effective_max_attempts_default_is_bounded(self):
        self.assertEqual(grok.compute_effective_max_attempts(1), 11)
        self.assertEqual(grok.compute_effective_max_attempts(5), 20)

    def test_compute_effective_max_attempts_respects_explicit_value(self):
        self.assertEqual(grok.compute_effective_max_attempts(10, max_attempts_arg=5), 5)
        self.assertEqual(grok.compute_effective_max_attempts(10, max_attempts_arg=15), 15)

    def test_reset_runtime_state_clears_compatibility_flags(self):
        grok.success_count = 2
        grok.attempt_count = 3
        grok.stop_event.set()
        grok.attempt_limit_reached.set()

        grok.reset_runtime_state()

        self.assertEqual(grok.success_count, 0)
        self.assertEqual(grok.attempt_count, 0)
        self.assertFalse(grok.stop_event.is_set())
        self.assertFalse(grok.attempt_limit_reached.is_set())

    def test_should_delete_email_after_registration(self):
        self.assertFalse(
            grok.should_delete_email_after_registration(
                registration_succeeded=True, keep_success_email=True
            )
        )
        self.assertTrue(
            grok.should_delete_email_after_registration(
                registration_succeeded=True, keep_success_email=False
            )
        )
        self.assertTrue(
            grok.should_delete_email_after_registration(
                registration_succeeded=False, keep_success_email=True
            )
        )

    def test_read_bool_env_accepts_true_false_strings(self):
        with patch.dict("os.environ", {"KEEP_SUCCESS_EMAIL": "false"}, clear=False):
            self.assertFalse(grok.read_bool_env("KEEP_SUCCESS_EMAIL", True))
        with patch.dict("os.environ", {"KEEP_SUCCESS_EMAIL": "true"}, clear=False):
            self.assertTrue(grok.read_bool_env("KEEP_SUCCESS_EMAIL", False))

    def test_read_bool_env_uses_default_when_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(grok.read_bool_env("KEEP_SUCCESS_EMAIL", False))
            self.assertTrue(grok.read_bool_env("KEEP_SUCCESS_EMAIL", True))

    def test_grok_module_all_exports_only_supported_compat_symbols(self):
        self.assertEqual(
            set(grok.__all__),
            {
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
            },
        )

    def test_main_returns_runner_code_and_syncs_compatibility_state(self):
        cfg = AppConfig(
            thread_count=2,
            target_count=3,
            max_attempts=12,
            keep_success_email=False,
            enable_nsfw=True,
            output_file="keys/test_output.txt",
            proxies={},
            metrics_path="logs/test.jsonl",
        )
        fake_runtime = RuntimeContext("site-key-new", "action-new", "state-tree-new")
        fake_stop = SimpleNamespace(
            success_count=3,
            attempt_count=7,
            stop_reason=StopReason.TARGET_REACHED,
        )
        fake_runner = SimpleNamespace(
            runtime=fake_runtime,
            stop=fake_stop,
            run=lambda: 0,
        )

        with patch("grok.build_main_config", return_value=cfg), patch(
            "grok.build_default_runtime_context", return_value=RuntimeContext("site-key-old", None, "state-tree-old")
        ), patch("grok.GrokRunner", return_value=fake_runner), patch("grok.os.makedirs"):
            code = grok.main(thread_count=2, total_count=3, max_attempts_arg=12, metrics_file="logs/test.jsonl")

        self.assertEqual(code, 0)
        self.assertEqual(grok.target_count, 3)
        self.assertEqual(grok.max_attempts, 12)
        self.assertEqual(grok.output_file, "keys/test_output.txt")
        self.assertEqual(grok.success_count, 3)
        self.assertEqual(grok.attempt_count, 7)
        self.assertFalse(grok.attempt_limit_reached.is_set())
        self.assertFalse(grok.stop_event.is_set())
        self.assertEqual(grok.config["site_key"], "site-key-new")
        self.assertEqual(grok.config["action_id"], "action-new")
        self.assertEqual(grok.config["state_tree"], "state-tree-new")

    def test_main_sets_attempt_limit_flag_when_runner_stops_due_to_limit(self):
        cfg = AppConfig(
            thread_count=1,
            target_count=2,
            max_attempts=5,
            keep_success_email=False,
            enable_nsfw=True,
            output_file="keys/test_limit.txt",
            proxies={},
            metrics_path="logs/test-limit.jsonl",
        )
        fake_runner = SimpleNamespace(
            runtime=RuntimeContext("site-key", "action-id", "state-tree"),
            stop=SimpleNamespace(
                success_count=1,
                attempt_count=5,
                stop_reason=StopReason.ATTEMPT_LIMIT,
            ),
            run=lambda: 1,
        )

        with patch("grok.build_main_config", return_value=cfg), patch(
            "grok.build_default_runtime_context", return_value=RuntimeContext("old-key", None, "old-tree")
        ), patch("grok.GrokRunner", return_value=fake_runner), patch("grok.os.makedirs"):
            code = grok.main(thread_count=1, total_count=2, max_attempts_arg=5, metrics_file="logs/test-limit.jsonl")

        self.assertEqual(code, 1)
        self.assertEqual(grok.success_count, 1)
        self.assertEqual(grok.attempt_count, 5)
        self.assertTrue(grok.attempt_limit_reached.is_set())
        self.assertTrue(grok.stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
