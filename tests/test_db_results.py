import unittest

from db_results import cleanup_old_results, load_result, results_db, save_result


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


if __name__ == "__main__":
    unittest.main()
