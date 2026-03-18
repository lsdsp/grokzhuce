import unittest


class SolverResultRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_result_payload_prefers_value_over_stale_status(self):
        from solver_result_repository import SolverResultRepository

        repo = SolverResultRepository()
        payload = repo.build_result_payload({"status": "CAPTCHA_NOT_READY", "value": "token-abc"})

        self.assertEqual(payload["errorId"], 0)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["solution"]["token"], "token-abc")

    async def test_build_result_payload_returns_unsolvable_for_captcha_fail(self):
        from solver_result_repository import SolverResultRepository

        repo = SolverResultRepository()
        payload = repo.build_result_payload({"status": "CAPTCHA_NOT_READY", "value": "CAPTCHA_FAIL"})

        self.assertEqual(payload["errorId"], 1)
        self.assertEqual(payload["errorCode"], "ERROR_CAPTCHA_UNSOLVABLE")

    async def test_build_result_payload_returns_processing_for_pending_status(self):
        from solver_result_repository import SolverResultRepository

        repo = SolverResultRepository()
        payload = repo.build_result_payload({"status": "CAPTCHA_NOT_READY"})

        self.assertEqual(payload["status"], "processing")


if __name__ == "__main__":
    unittest.main()
