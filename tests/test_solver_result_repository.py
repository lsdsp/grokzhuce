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


if __name__ == "__main__":
    unittest.main()
