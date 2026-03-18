import asyncio
import os
from typing import Optional

from patchright.async_api import async_playwright

from browser_configs import browser_config

try:
    from camoufox.async_api import AsyncCamoufox
except Exception:
    AsyncCamoufox = None


class BrowserPoolManager:
    def __init__(
        self,
        *,
        headless: bool,
        browser_type: str,
        thread_count: int,
        debug: bool,
        proxy_support: bool,
        useragent: Optional[str],
        use_random_config: bool,
        browser_name: Optional[str],
        browser_version: Optional[str],
        base_dir: Optional[str] = None,
        logger=None,
    ):
        self.debug = debug
        self.browser_type = browser_type
        self.headless = headless
        self.thread_count = thread_count
        self.proxy_support = proxy_support
        self.browser_pool = asyncio.Queue()
        self.use_random_config = use_random_config
        self.browser_name = browser_name
        self.browser_version = browser_version
        self.base_dir = base_dir or os.getcwd()
        self.logger = logger
        self._playwright = None
        self._camoufox = None
        self.useragent = useragent
        self.sec_ch_ua = None

        if self.browser_type in ["chromium", "chrome", "msedge"]:
            if browser_name and browser_version:
                config = browser_config.get_browser_config(browser_name, browser_version)
                if config:
                    useragent, sec_ch_ua = config
                    self.useragent = useragent
                    self.sec_ch_ua = sec_ch_ua
            elif useragent:
                self.useragent = useragent
            else:
                browser, version, useragent, sec_ch_ua = browser_config.get_random_browser_config(self.browser_type)
                self.browser_name = browser
                self.browser_version = version
                self.useragent = useragent
                self.sec_ch_ua = sec_ch_ua

    def _log(self, level: str, message: str):
        if self.logger is None:
            return
        target = getattr(self.logger, level, None)
        if callable(target):
            target(message)

    async def initialize(self) -> None:
        self._playwright = None
        self._camoufox = None

        if self.browser_type in ["chromium", "chrome", "msedge"]:
            self._playwright = await async_playwright().start()
        elif self.browser_type == "camoufox":
            if AsyncCamoufox is None:
                raise RuntimeError("camoufox is not installed. Install it or use --browser_type chromium.")
            self._camoufox = AsyncCamoufox(headless=self.headless)

        browser_configs = []
        for _ in range(self.thread_count):
            if self.browser_type in ["chromium", "chrome", "msedge"]:
                if self.use_random_config:
                    browser, version, useragent, sec_ch_ua = browser_config.get_random_browser_config(self.browser_type)
                elif self.browser_name and self.browser_version:
                    config = browser_config.get_browser_config(self.browser_name, self.browser_version)
                    if config:
                        useragent, sec_ch_ua = config
                        browser = self.browser_name
                        version = self.browser_version
                    else:
                        browser, version, useragent, sec_ch_ua = browser_config.get_random_browser_config(self.browser_type)
                else:
                    browser = getattr(self, "browser_name", "custom")
                    version = getattr(self, "browser_version", "custom")
                    useragent = self.useragent
                    sec_ch_ua = getattr(self, "sec_ch_ua", "")
            else:
                browser = self.browser_type
                version = "custom"
                useragent = self.useragent
                sec_ch_ua = getattr(self, "sec_ch_ua", "")

            browser_configs.append(
                {
                    "browser_name": browser,
                    "browser_version": version,
                    "useragent": useragent,
                    "sec_ch_ua": sec_ch_ua,
                }
            )

        for index, config in enumerate(browser_configs, start=1):
            browser = await self.spawn_browser_for_config(index=index, config=config)
            if browser:
                await self.browser_pool.put((index, browser, config))
            if self.debug:
                self._log("info", f"Browser {index} initialized successfully with {config['browser_name']} {config['browser_version']}")

        self._log("info", f"Browser pool initialized with {self.browser_pool.qsize()} browsers")

    async def spawn_browser_for_config(self, index: int, config: dict):
        browser_args = [
            "--window-position=0,0",
            "--force-device-scale-factor=1",
        ]
        if config.get("useragent"):
            browser_args.append(f"--user-agent={config['useragent']}")

        try:
            if self.browser_type in ["chromium", "chrome", "msedge"]:
                if not self._playwright:
                    self._log("error", f"Browser {index}: Playwright launcher is not initialized")
                    return None
                return await self._playwright.chromium.launch(
                    channel=self.browser_type,
                    headless=self.headless,
                    args=browser_args,
                )
            if self.browser_type == "camoufox":
                if not self._camoufox:
                    self._log("error", f"Browser {index}: Camoufox launcher is not initialized")
                    return None
                return await self._camoufox.start()
        except Exception as exc:
            self._log("error", f"Browser {index}: Failed to spawn replacement browser: {exc}")
            return None
        return None

    async def return_or_replace_browser(self, index: int, browser, browser_config: dict):
        if not hasattr(browser, "is_connected"):
            await self.browser_pool.put((index, browser, browser_config))
            if self.debug:
                self._log("debug", f"Browser {index}: Browser returned to pool (no is_connected attribute)")
            return

        try:
            if browser.is_connected():
                await self.browser_pool.put((index, browser, browser_config))
                if self.debug:
                    self._log("debug", f"Browser {index}: Browser returned to pool")
                return
        except Exception as exc:
            if self.debug:
                self._log("warning", f"Browser {index}: Error checking browser connection: {exc}")

        if self.debug:
            self._log("warning", f"Browser {index}: Browser disconnected, trying to replace it")

        replacement = await self.spawn_browser_for_config(index=index, config=browser_config)
        if replacement:
            await self.browser_pool.put((index, replacement, browser_config))
            self._log("info", f"Browser {index}: Replaced disconnected browser in pool")
        else:
            self._log("error", f"Browser {index}: Replacement failed, browser pool size may decrease")
