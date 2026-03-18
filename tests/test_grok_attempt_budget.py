import unittest
from unittest.mock import patch

import grok


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


if __name__ == "__main__":
    unittest.main()
