import unittest
from importlib import reload
from unittest.mock import patch

from db_results import (
    DEFAULT_RESULT_STORE,
    cleanup_old_results,
    load_result,
    load_solver_result,
    results_db,
    save_result,
    save_solver_result,
)


class DbResultsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        results_db.clear()

    async def test_save_result_preserves_create_time_on_updates(self):
        await save_result("task-1", "turnstile", {"status": "CAPTCHA_NOT_READY", "createTime": 123})
        await save_result("task-1", "turnstile", {"value": "token-abc", "elapsed_time": 1.23})

        result = await load_result("task-1")
        self.assertIsNotNone(result)
        self.assertEqual(result["createTime"], 123)
        self.assertEqual(result["value"], "token-abc")
        self.assertEqual(result["taskType"], "turnstile")
        self.assertNotIn("status", result)

    async def test_cleanup_old_results_removes_expired_records(self):
        await save_result("old", "turnstile", {"createTime": 1, "value": "CAPTCHA_FAIL"})
        await save_result("new", "turnstile", {"createTime": 4_102_444_800, "value": "CAPTCHA_NOT_READY"})

        deleted = await cleanup_old_results(days_old=7)

        self.assertEqual(deleted, 1)
        self.assertIsNone(await load_result("old"))
        self.assertIsNotNone(await load_result("new"))

    async def test_db_results_can_select_sqlite_default_store(self):
        import db_results

        with patch.dict(
            "os.environ",
            {
                "SOLVER_RESULT_STORE": "sqlite",
                "SOLVER_RESULT_DB_PATH": ":memory:",
            },
            clear=False,
        ):
            reloaded = reload(db_results)

        self.assertEqual(reloaded.default_result_store.__class__.__name__, "SQLiteSolverResultStore")
        with patch.dict("os.environ", {"SOLVER_RESULT_STORE": "memory"}, clear=False):
            reload(db_results)

    async def test_new_solver_result_aliases_share_default_store(self):
        self.assertIsNotNone(DEFAULT_RESULT_STORE)

        await save_solver_result("task-2", "turnstile", {"value": "token-xyz", "createTime": 456})
        result = await load_solver_result("task-2")

        self.assertEqual(result["value"], "token-xyz")
        self.assertEqual(result["createTime"], 456)


if __name__ == "__main__":
    unittest.main()
