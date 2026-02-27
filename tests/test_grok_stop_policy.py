import json
import os
import tempfile
import unittest

import grok


class GrokStopPolicyTests(unittest.TestCase):
    def test_claim_attempt_slot_returns_struct_and_enforces_limit(self):
        policy = grok.StopPolicy(target_count=5, max_attempts=2)

        claim1 = policy.claim_attempt_slot()
        claim2 = policy.claim_attempt_slot()
        claim3 = policy.claim_attempt_slot()

        self.assertTrue(claim1.allowed)
        self.assertEqual(claim1.slot_no, 1)
        self.assertTrue(claim2.allowed)
        self.assertEqual(claim2.slot_no, 2)
        self.assertFalse(claim3.allowed)
        self.assertEqual(claim3.reason, grok.StopReason.ATTEMPT_LIMIT)
        self.assertTrue(policy.should_stop())

    def test_mark_success_stops_when_target_reached(self):
        policy = grok.StopPolicy(target_count=2, max_attempts=10)
        self.assertEqual(policy.mark_success(), 1)
        self.assertFalse(policy.should_stop())
        self.assertEqual(policy.mark_success(), 2)
        self.assertTrue(policy.should_stop())
        self.assertEqual(policy.stop_reason, grok.StopReason.TARGET_REACHED)

    def test_jsonl_logger_writes_json_line(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "metrics.jsonl")
            logger = grok.JsonlLogger(path)
            logger.event("INFO", "stage_a", "hello", thread_id=1, attempt_no=2)

            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["level"], "INFO")
            self.assertEqual(payload["stage"], "stage_a")
            self.assertEqual(payload["thread_id"], 1)
            self.assertEqual(payload["attempt_no"], 2)


if __name__ == "__main__":
    unittest.main()
