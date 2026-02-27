import unittest
from unittest.mock import AsyncMock, Mock, patch

from api_solver import TurnstileAPIServer


class ApiSolverResultTests(unittest.IsolatedAsyncioTestCase):
    def _build_server(self):
        return TurnstileAPIServer(
            headless=True,
            useragent=None,
            debug=False,
            browser_type="camoufox",
            thread=1,
            proxy_support=False,
        )

    async def test_get_result_prefers_value_over_stale_not_ready_status(self):
        server = self._build_server()
        mocked_result = {"status": "CAPTCHA_NOT_READY", "value": "token-abc"}

        with patch("api_solver.load_result", new=AsyncMock(return_value=mocked_result)):
            async with server.app.test_request_context("/result?id=task-1"):
                response, status_code = await server.get_result()

        payload = await response.get_json()
        self.assertEqual(status_code, 200)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["solution"]["token"], "token-abc")

    async def test_get_result_returns_unsolvable_for_captcha_fail_even_with_stale_status(self):
        server = self._build_server()
        mocked_result = {"status": "CAPTCHA_NOT_READY", "value": "CAPTCHA_FAIL"}

        with patch("api_solver.load_result", new=AsyncMock(return_value=mocked_result)):
            async with server.app.test_request_context("/result?id=task-2"):
                response, status_code = await server.get_result()

        payload = await response.get_json()
        self.assertEqual(status_code, 200)
        self.assertEqual(payload["errorId"], 1)
        self.assertEqual(payload["errorCode"], "ERROR_CAPTCHA_UNSOLVABLE")

    async def test_return_or_replace_browser_requeues_connected_browser(self):
        server = self._build_server()
        browser = Mock()
        browser.is_connected.return_value = True

        await server._return_or_replace_browser(
            index=1,
            browser=browser,
            browser_config={"useragent": "ua", "sec_ch_ua": ""},
        )

        queued_index, queued_browser, queued_config = await server.browser_pool.get()
        self.assertEqual(queued_index, 1)
        self.assertIs(queued_browser, browser)
        self.assertEqual(queued_config["useragent"], "ua")

    async def test_return_or_replace_browser_spawns_replacement_when_disconnected(self):
        server = self._build_server()
        browser = Mock()
        browser.is_connected.return_value = False
        replacement = Mock()

        with patch.object(server, "_spawn_browser_for_config", new=AsyncMock(return_value=replacement)) as spawn_mock:
            await server._return_or_replace_browser(
                index=2,
                browser=browser,
                browser_config={"useragent": "ua2", "sec_ch_ua": ""},
            )

        spawn_mock.assert_awaited_once()
        queued_index, queued_browser, queued_config = await server.browser_pool.get()
        self.assertEqual(queued_index, 2)
        self.assertIs(queued_browser, replacement)
        self.assertEqual(queued_config["useragent"], "ua2")


if __name__ == "__main__":
    unittest.main()
