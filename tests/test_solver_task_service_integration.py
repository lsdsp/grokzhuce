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


class _BoomPage(_FakePage):
    async def goto(self, _url, wait_until="domcontentloaded", timeout=30000):
        raise RuntimeError("navigation exploded")


class _FakeContext:
    def __init__(self, page=None):
        self.page = page or _FakePage()

    async def new_page(self):
        return self.page

    async def close(self):
        return None


class _FakeBrowser:
    def __init__(self, page=None):
        self.page = page or _FakePage()

    def is_connected(self):
        return True

    async def new_context(self, **_kwargs):
        return _FakeContext(self.page)


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
            event_logger=Mock(),
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

    async def test_solve_failure_persists_diagnostics(self):
        repository = SolverResultRepository(store=InMemorySolverResultStore())
        await repository.init()

        pool_manager = Mock()
        pool_manager.proxy_support = False
        pool_manager.browser_type = "camoufox"
        pool_manager.base_dir = "."
        pool_manager.browser_pool = asyncio.Queue()
        await pool_manager.browser_pool.put(
            (4, _FakeBrowser(page=_BoomPage()), {"useragent": "ua-test", "sec_ch_ua": ""})
        )
        pool_manager.return_or_replace_browser = AsyncMock()
        pool_manager.spawn_browser_for_config = AsyncMock()

        service = TurnstileTaskService(
            pool_manager=pool_manager,
            repository=repository,
            logger=Mock(),
            event_logger=Mock(),
            colors={"MAGENTA": "", "RESET": "", "GREEN": "", "RED": ""},
            debug=False,
            antishadow_inject=AsyncMock(),
            block_rendering=AsyncMock(),
            unblock_rendering=AsyncMock(),
            inject_captcha_directly=AsyncMock(),
            try_click_strategies=AsyncMock(return_value=True),
        )

        await service.solve_turnstile(task_id="task-fail", url="https://example.com", sitekey="site-key")
        payload = await service.get_result_payload("task-fail")

        self.assertEqual(payload["errorId"], 1)
        self.assertEqual(payload["diagnostics"]["failure_reason"], "navigation_exploded")
        self.assertEqual(payload["diagnostics"]["failed_stage"], "navigate")
        self.assertEqual(payload["diagnostics"]["browser_index"], 4)
        pool_manager.return_or_replace_browser.assert_awaited_once()

    async def test_success_and_failure_emit_structured_events(self):
        repository = SolverResultRepository(store=InMemorySolverResultStore())
        await repository.init()
        event_logger = Mock()

        success_pool = Mock()
        success_pool.proxy_support = False
        success_pool.browser_type = "camoufox"
        success_pool.base_dir = "."
        success_pool.browser_pool = asyncio.Queue()
        await success_pool.browser_pool.put(
            (1, _FakeBrowser(), {"useragent": "ua-test", "sec_ch_ua": "", "browser_name": "camoufox", "browser_version": "custom"})
        )
        success_pool.return_or_replace_browser = AsyncMock()
        success_pool.spawn_browser_for_config = AsyncMock()

        success_service = TurnstileTaskService(
            pool_manager=success_pool,
            repository=repository,
            logger=Mock(),
            event_logger=event_logger,
            colors={"MAGENTA": "", "RESET": "", "GREEN": "", "RED": ""},
            debug=False,
            antishadow_inject=AsyncMock(),
            block_rendering=AsyncMock(),
            unblock_rendering=AsyncMock(),
            inject_captcha_directly=AsyncMock(),
            try_click_strategies=AsyncMock(return_value=True),
        )
        await success_service.solve_turnstile(task_id="task-success", url="https://example.com", sitekey="site-key")

        failure_pool = Mock()
        failure_pool.proxy_support = False
        failure_pool.browser_type = "camoufox"
        failure_pool.base_dir = "."
        failure_pool.browser_pool = asyncio.Queue()
        await failure_pool.browser_pool.put(
            (4, _FakeBrowser(page=_BoomPage()), {"useragent": "ua-test", "sec_ch_ua": "", "browser_name": "camoufox", "browser_version": "custom"})
        )
        failure_pool.return_or_replace_browser = AsyncMock()
        failure_pool.spawn_browser_for_config = AsyncMock()

        failure_service = TurnstileTaskService(
            pool_manager=failure_pool,
            repository=repository,
            logger=Mock(),
            event_logger=event_logger,
            colors={"MAGENTA": "", "RESET": "", "GREEN": "", "RED": ""},
            debug=False,
            antishadow_inject=AsyncMock(),
            block_rendering=AsyncMock(),
            unblock_rendering=AsyncMock(),
            inject_captcha_directly=AsyncMock(),
            try_click_strategies=AsyncMock(return_value=True),
        )
        await failure_service.solve_turnstile(task_id="task-failure", url="https://example.com", sitekey="site-key")

        calls = event_logger.event.call_args_list
        success_call = next(call for call in calls if call.args[:3] == ("info", "solver_success", "captcha solved"))
        failure_call = next(call for call in calls if call.args[:3] == ("error", "solver_failure", "captcha solve failed"))

        self.assertEqual(success_call.kwargs["task_id"], "task-success")
        self.assertEqual(success_call.kwargs["browser_index"], 1)
        self.assertEqual(success_call.kwargs["latency_ms"] >= 0, True)
        self.assertEqual(failure_call.kwargs["task_id"], "task-failure")
        self.assertEqual(failure_call.kwargs["error_type"], "captcha")
        self.assertEqual(failure_call.kwargs["failed_stage"], "navigate")

    async def test_save_failure_redacts_proxy_before_emitting_structured_event(self):
        repository = SolverResultRepository(store=InMemorySolverResultStore())
        await repository.init()
        event_logger = Mock()

        pool_manager = Mock()
        pool_manager.proxy_support = False
        pool_manager.browser_type = "camoufox"
        pool_manager.base_dir = "."
        pool_manager.browser_pool = asyncio.Queue()
        pool_manager.return_or_replace_browser = AsyncMock()
        pool_manager.spawn_browser_for_config = AsyncMock()

        service = TurnstileTaskService(
            pool_manager=pool_manager,
            repository=repository,
            logger=Mock(),
            event_logger=event_logger,
            colors={"MAGENTA": "", "RESET": "", "GREEN": "", "RED": ""},
            debug=False,
            antishadow_inject=AsyncMock(),
            block_rendering=AsyncMock(),
            unblock_rendering=AsyncMock(),
            inject_captcha_directly=AsyncMock(),
            try_click_strategies=AsyncMock(return_value=True),
        )

        await service._save_failure(
            "task-proxy",
            elapsed_time=1.0,
            failed_stage="navigate",
            failure_reason="proxy_auth_failed",
            browser_index=2,
            proxy="http:127.0.0.1:8080:user:pass",
        )

        failure_call = event_logger.event.call_args
        self.assertEqual(failure_call.args[:3], ("error", "solver_failure", "captcha solve failed"))
        self.assertEqual(failure_call.kwargs["proxy"], "http:127.0.0.1:8080:***:***")
        self.assertNotIn("user:pass", failure_call.kwargs["proxy"])


if __name__ == "__main__":
    unittest.main()
