import unittest

from oneclick_shared import DEFAULTS, FAILURE_PATTERNS, get_defaults, get_failure_patterns


class OneClickSharedTests(unittest.TestCase):
    def test_defaults_expose_required_runtime_settings(self):
        defaults = get_defaults()

        for key in (
            "DEFAULT_THREADS",
            "DEFAULT_COUNT",
            "DEFAULT_SOLVER_THREAD",
            "DEFAULT_PROXY_HTTP",
            "DEFAULT_PROXY_SOCKS",
            "SOLVER_READY_TIMEOUT_SEC",
            "SOLVER_STOP_TIMEOUT_SEC",
            "LOG_ROOT_DIR",
            "LOG_SOLVER_DIR",
            "LOG_GROK_DIR",
            "LOG_ONECLICK_DIR",
            "LOG_OTHERS_DIR",
        ):
            self.assertIn(key, defaults)

        self.assertEqual(defaults, DEFAULTS)

    def test_failure_patterns_include_attempt_limit_and_bootstrap_errors(self):
        patterns = get_failure_patterns()

        self.assertIn("ATTEMPT_LIMIT_REACHED", patterns)
        self.assertIn("未找到 Action ID", patterns)
        self.assertEqual(patterns, FAILURE_PATTERNS)


if __name__ == "__main__":
    unittest.main()
