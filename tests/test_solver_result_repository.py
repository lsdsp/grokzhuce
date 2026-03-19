import unittest
from unittest.mock import AsyncMock, Mock


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

    async def test_build_result_payload_includes_failure_diagnostics(self):
        from solver_result_repository import SolverResultRepository

        repo = SolverResultRepository()
        payload = repo.build_result_payload(
            {
                "value": "CAPTCHA_FAIL",
                "elapsed_time": 9.5,
                "failure_reason": "token_not_found",
                "failed_stage": "poll_for_token",
                "browser_index": 2,
                "proxy": "http://proxy.example:8080",
            }
        )

        self.assertEqual(payload["errorId"], 1)
        self.assertEqual(payload["errorCode"], "ERROR_CAPTCHA_UNSOLVABLE")
        self.assertEqual(payload["diagnostics"]["failure_reason"], "token_not_found")
        self.assertEqual(payload["diagnostics"]["failed_stage"], "poll_for_token")
        self.assertEqual(payload["diagnostics"]["browser_index"], 2)
        self.assertEqual(payload["diagnostics"]["elapsed_time"], 9.5)

    async def test_build_result_payload_redacts_proxy_credentials_in_failure_diagnostics(self):
        from solver_result_repository import SolverResultRepository

        repo = SolverResultRepository()
        payload = repo.build_result_payload(
            {
                "value": "CAPTCHA_FAIL",
                "failure_reason": "page_goto_failed",
                "proxy": "http://user:pass@proxy.example:8080",
            }
        )

        self.assertEqual(payload["diagnostics"]["proxy"], "http://***:***@proxy.example:8080")
        self.assertNotIn("user:pass@", payload["diagnostics"]["proxy"])

    async def test_build_result_payload_redacts_colon_format_proxy_credentials(self):
        from solver_result_repository import SolverResultRepository

        repo = SolverResultRepository()
        payload = repo.build_result_payload(
            {
                "value": "CAPTCHA_FAIL",
                "failure_reason": "proxy_auth_failed",
                "proxy": "http:127.0.0.1:8080:user:pass",
            }
        )

        self.assertEqual(payload["diagnostics"]["proxy"], "http:127.0.0.1:8080:***:***")
        self.assertNotIn("user:pass", payload["diagnostics"]["proxy"])

    async def test_build_result_payload_returns_processing_for_pending_status(self):
        from solver_result_repository import SolverResultRepository

        repo = SolverResultRepository()
        payload = repo.build_result_payload({"status": "CAPTCHA_NOT_READY"})

        self.assertEqual(payload["status"], "processing")

    async def test_repository_supports_injected_store_backend(self):
        from solver_result_repository import SolverResultRepository

        store = Mock()
        store.init = AsyncMock()
        store.save = AsyncMock()
        store.load = AsyncMock(return_value={"value": "token-abc"})
        store.cleanup = AsyncMock(return_value=3)

        repo = SolverResultRepository(store=store)

        await repo.init()
        await repo.save_pending("task-1", url="https://example.com", sitekey="site-key")
        await repo.save_token("task-1", token="token-abc", elapsed_time=1.2)
        await repo.save_failure("task-2", elapsed_time=2.4)
        result = await repo.load("task-1")
        deleted = await repo.cleanup(days_old=9)

        store.init.assert_awaited_once()
        self.assertEqual(store.save.await_count, 3)
        store.load.assert_awaited_once_with("task-1")
        store.cleanup.assert_awaited_once_with(days_old=9)
        self.assertEqual(result["value"], "token-abc")
        self.assertEqual(deleted, 3)

    async def test_save_failure_forwards_diagnostic_context(self):
        from solver_result_repository import SolverResultRepository

        store = Mock()
        store.init = AsyncMock()
        store.save = AsyncMock()
        store.load = AsyncMock(return_value=None)
        store.cleanup = AsyncMock(return_value=0)
        repo = SolverResultRepository(store=store)

        await repo.save_failure(
            "task-9",
            elapsed_time=2.4,
            failure_reason="page_goto_failed",
            failed_stage="navigate",
            browser_index=1,
        )

        store.save.assert_awaited_once_with(
            "task-9",
            "turnstile",
            {
                "value": "CAPTCHA_FAIL",
                "elapsed_time": 2.4,
                "failure_reason": "page_goto_failed",
                "failed_stage": "navigate",
                "browser_index": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
