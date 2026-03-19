import tempfile
import unittest
from pathlib import Path


class SolverResultStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_store_persists_and_merges_results(self):
        from solver_result_store import SQLiteSolverResultStore

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "solver-results.sqlite3"
            store = SQLiteSolverResultStore(str(db_path))

            await store.init()
            await store.save("task-1", "turnstile", {"status": "CAPTCHA_NOT_READY", "createTime": 123})
            await store.save("task-1", "turnstile", {"value": "token-abc", "elapsed_time": 1.5})

            result = await store.load("task-1")
            store.close()

        self.assertEqual(result["createTime"], 123)
        self.assertEqual(result["value"], "token-abc")
        self.assertEqual(result["taskType"], "turnstile")
        self.assertNotIn("status", result)

    async def test_sqlite_store_cleanup_removes_expired_records(self):
        from solver_result_store import SQLiteSolverResultStore

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "solver-results.sqlite3"
            store = SQLiteSolverResultStore(str(db_path))

            await store.init()
            await store.save("old", "turnstile", {"createTime": 1, "value": "CAPTCHA_FAIL"})
            await store.save("new", "turnstile", {"createTime": 4_102_444_800, "value": "token-abc"})

            deleted = await store.cleanup(days_old=7)
            old_result = await store.load("old")
            new_result = await store.load("new")
            store.close()

        self.assertEqual(deleted, 1)
        self.assertIsNone(old_result)
        self.assertIsNotNone(new_result)
