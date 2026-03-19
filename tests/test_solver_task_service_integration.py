import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from solver_result_repository import SolverResultRepository
from solver_result_store import InMemorySolverResultStore
from solver_task_service import TurnstileTaskService


class _FakeLocator:
    async def count(self):
        return 1

    async def input_value(self, timeout=500):
        return "token-from-fake-page"

    def nth(self, _index):
        return self


class _FakePage:
    def locator(self, _selector):
        return _FakeLocator()

    async def add_init_script(self, _script):
        return None

    async def set_viewport_size(self, _size):
        return None

    async def goto(self, _url, wait_until="domcontentloaded", timeout=30000):
        return None


class _FakeContext:
    def __init__(self):
        self.page = _FakePage()

    async def new_page(self):
        return self.page

    async def close(self):
        return None


class _FakeBrowser:
    def is_connected(self):
        return True

    async def new_context(self, **_kwargs):
        return _FakeContext()


class SolverTaskServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_solve_and_read_result_payload(self):
        repository = SolverResultRepository(store=InMemorySolverResultStore())
        await repository.init()

        pool_manager = Mock()
        pool_manager.proxy_support = False
        pool_manager.browser_type = "camoufox"
        pool_manager.base_dir = "."
        pool_manager.browser_pool = asyncio.Queue()
        await pool_manager.browser_pool.put(
            (1, _FakeBrowser(), {"useragent": "ua-test", "sec_ch_ua": ""})
        )
        pool_manager.return_or_replace_browser = AsyncMock()
        pool_manager.spawn_browser_for_config = AsyncMock()

        service = TurnstileTaskService(
            pool_manager=pool_manager,
            repository=repository,
            logger=Mock(),
            colors={"MAGENTA": "", "RESET": "", "GREEN": "", "RED": ""},
            debug=False,
            antishadow_inject=AsyncMock(),
            block_rendering=AsyncMock(),
            unblock_rendering=AsyncMock(),
            inject_captcha_directly=AsyncMock(),
            try_click_strategies=AsyncMock(return_value=True),
        )

        created_tasks = []
        original_create_task = asyncio.create_task

        def _capture_task(coro):
            task = original_create_task(coro)
            created_tasks.append(task)
            return task

        with patch("solver_task_service.asyncio.sleep", new=AsyncMock()), patch(
            "solver_task_service.asyncio.create_task",
            side_effect=_capture_task,
        ):
            task_id = await service.enqueue_task(
                url="https://example.com",
                sitekey="site-key",
                action="signup",
                cdata="sample",
            )

            self.assertEqual(len(created_tasks), 1)
            await created_tasks[0]

        payload = await service.get_result_payload(task_id)

        self.assertEqual(payload["errorId"], 0)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["solution"]["token"], "token-from-fake-page")
        pool_manager.return_or_replace_browser.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
