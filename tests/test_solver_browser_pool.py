import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch


class BrowserPoolManagerTests(unittest.IsolatedAsyncioTestCase):
    def _build_pool(self):
        from solver_browser_pool import BrowserPoolManager

        return BrowserPoolManager(
            headless=True,
            browser_type="camoufox",
            thread_count=1,
            debug=False,
            proxy_support=False,
            useragent=None,
            use_random_config=False,
            browser_name=None,
            browser_version=None,
        )

    async def test_return_or_replace_browser_requeues_connected_browser(self):
        pool = self._build_pool()
        browser = Mock()
        browser.is_connected.return_value = True

        await pool.return_or_replace_browser(
            index=1,
            browser=browser,
            browser_config={"useragent": "ua", "sec_ch_ua": ""},
        )

        queued_index, queued_browser, queued_config = await asyncio.wait_for(pool.browser_pool.get(), timeout=1)
        self.assertEqual(queued_index, 1)
        self.assertIs(queued_browser, browser)
        self.assertEqual(queued_config["useragent"], "ua")

    async def test_return_or_replace_browser_spawns_replacement_when_disconnected(self):
        pool = self._build_pool()
        browser = Mock()
        browser.is_connected.return_value = False
        replacement = Mock()

        with patch.object(pool, "spawn_browser_for_config", new=AsyncMock(return_value=replacement)) as spawn_mock:
            await pool.return_or_replace_browser(
                index=2,
                browser=browser,
                browser_config={"useragent": "ua2", "sec_ch_ua": ""},
            )

        spawn_mock.assert_awaited_once()
        queued_index, queued_browser, queued_config = await asyncio.wait_for(pool.browser_pool.get(), timeout=1)
        self.assertEqual(queued_index, 2)
        self.assertIs(queued_browser, replacement)
        self.assertEqual(queued_config["useragent"], "ua2")


if __name__ == "__main__":
    unittest.main()
