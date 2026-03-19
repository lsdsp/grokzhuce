import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import grok
import grok_compat
from grok_runtime import StopReason


class GrokCompatTests(unittest.TestCase):
    def setUp(self):
        grok.reset_runtime_state()
        grok_compat.state.target_count = 100
        grok_compat.state.max_attempts = 0
        grok_compat.state.output_file = None
        grok_compat.state.config.update(
            {
                "site_key": "0x4AAAAAAAhr9JGVDZbrZOo0",
                "action_id": None,
                "state_tree": grok_compat.state.config["state_tree"],
            }
        )

    def test_grok_module_assignment_updates_shared_compat_state(self):
        grok.success_count = 5
        grok.attempt_count = 8
        grok.target_count = 12
        grok.max_attempts = 40
        grok.output_file = "keys/demo.txt"
        grok.stop_event = threading.Event()
        grok.attempt_limit_reached = threading.Event()

        self.assertEqual(grok_compat.state.success_count, 5)
        self.assertEqual(grok_compat.state.attempt_count, 8)
        self.assertEqual(grok_compat.state.target_count, 12)
        self.assertEqual(grok_compat.state.max_attempts, 40)
        self.assertEqual(grok_compat.state.output_file, "keys/demo.txt")
        self.assertIs(grok.stop_event, grok_compat.state.stop_event)
        self.assertIs(grok.attempt_limit_reached, grok_compat.state.attempt_limit_reached)

    def test_reset_runtime_state_resets_shared_compat_state(self):
        old_start_time = grok.start_time
        grok.success_count = 2
        grok.attempt_count = 3
        grok.stop_event.set()
        grok.attempt_limit_reached.set()

        with patch("grok_compat.time.time", return_value=old_start_time + 10):
            grok.reset_runtime_state()

        self.assertEqual(grok_compat.state.success_count, 0)
        self.assertEqual(grok_compat.state.attempt_count, 0)
        self.assertEqual(grok.start_time, old_start_time + 10)
        self.assertFalse(grok_compat.state.stop_event.is_set())
        self.assertFalse(grok_compat.state.attempt_limit_reached.is_set())

    def test_grok_module_exposes_start_time_through_compat_proxy(self):
        self.assertEqual(grok.start_time, grok_compat.state.start_time)

    def test_sync_runner_state_updates_shared_state(self):
        runner = SimpleNamespace(
            runtime=SimpleNamespace(site_key="site-key", action_id="action-id", state_tree="state-tree"),
            stop=SimpleNamespace(success_count=1, attempt_count=6, stop_reason=StopReason.ATTEMPT_LIMIT),
        )

        grok_compat.sync_runner_state(runner)

        self.assertEqual(grok.success_count, 1)
        self.assertEqual(grok.attempt_count, 6)
        self.assertEqual(grok.config["site_key"], "site-key")
        self.assertEqual(grok.config["action_id"], "action-id")
        self.assertEqual(grok.config["state_tree"], "state-tree")
        self.assertTrue(grok.attempt_limit_reached.is_set())
        self.assertTrue(grok.stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
