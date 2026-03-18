import asyncio
import os
import random
import time
import uuid
from typing import Optional


class TurnstileTaskService:
    def __init__(
        self,
        *,
        pool_manager,
        repository,
        logger,
        colors,
        debug: bool,
        antishadow_inject,
        block_rendering,
        unblock_rendering,
        inject_captcha_directly,
        try_click_strategies,
    ):
        self.pool_manager = pool_manager
        self.repository = repository
        self.logger = logger
        self.colors = colors
        self.debug = debug
        self.antishadow_inject = antishadow_inject
        self.block_rendering = block_rendering
        self.unblock_rendering = unblock_rendering
        self.inject_captcha_directly = inject_captcha_directly
        self.try_click_strategies = try_click_strategies

    async def enqueue_task(self, *, url: str, sitekey: str, action: Optional[str] = None, cdata: Optional[str] = None) -> str:
        task_id = str(uuid.uuid4())
        await self.repository.save_pending(task_id, url=url, sitekey=sitekey, action=action, cdata=cdata)
        asyncio.create_task(self.solve_turnstile(task_id=task_id, url=url, sitekey=sitekey, action=action, cdata=cdata))
        return task_id

    async def get_result_payload(self, task_id: str):
        result = await self.repository.load(task_id)
        return self.repository.build_result_payload(result)

    async def solve_turnstile(self, task_id: str, url: str, sitekey: str, action: Optional[str] = None, cdata: Optional[str] = None):
        proxy = None
        context = None
        start_time = time.time()

        index, browser, browser_config = await self.pool_manager.browser_pool.get()

        try:
            try:
                if hasattr(browser, "is_connected") and not browser.is_connected():
                    if self.debug:
                        self.logger.warning(f"Browser {index}: Browser disconnected, recreating")
                    replacement = await self.pool_manager.spawn_browser_for_config(index=index, config=browser_config)
                    if not replacement:
                        await self.repository.save_failure(task_id, elapsed_time=0)
                        return
                    browser = replacement
                    if self.debug:
                        self.logger.info(f"Browser {index}: Replacement browser created")
            except Exception as exc:
                if self.debug:
                    self.logger.warning(f"Browser {index}: Cannot check browser state: {str(exc)}")

            context_options = {"user_agent": browser_config["useragent"]}
            if browser_config["sec_ch_ua"] and browser_config["sec_ch_ua"].strip():
                context_options["extra_http_headers"] = {"sec-ch-ua": browser_config["sec_ch_ua"]}

            if self.pool_manager.proxy_support:
                proxy_file_path = os.path.join(self.pool_manager.base_dir, "proxies.txt")
                try:
                    with open(proxy_file_path, encoding="utf-8") as proxy_file:
                        proxies = [line.strip() for line in proxy_file if line.strip()]
                    proxy = random.choice(proxies) if proxies else None
                    if self.debug and proxy:
                        self.logger.debug(f"Browser {index}: Selected proxy: {proxy}")
                    elif self.debug and not proxy:
                        self.logger.debug(f"Browser {index}: No proxies available")
                except FileNotFoundError:
                    self.logger.warning(f"Proxy file not found: {proxy_file_path}")
                    proxy = None
                except Exception as exc:
                    self.logger.error(f"Error reading proxy file: {str(exc)}")
                    proxy = None

                if proxy:
                    parsed_proxy = None
                    if "@" in proxy:
                        try:
                            scheme_part, auth_part = proxy.split("://", 1)
                            auth, address = auth_part.split("@", 1)
                            username, password = auth.split(":", 1)
                            ip, port = address.rsplit(":", 1)
                            parsed_proxy = {
                                "server": f"{scheme_part}://{ip}:{port}",
                                "username": username,
                                "password": password,
                            }
                        except ValueError:
                            self.logger.warning(f"Browser {index}: Invalid proxy format: {proxy}")
                    else:
                        parts = proxy.split(":")
                        if len(parts) == 5:
                            proxy_scheme, proxy_ip, proxy_port, proxy_user, proxy_pass = parts
                            parsed_proxy = {
                                "server": f"{proxy_scheme}://{proxy_ip}:{proxy_port}",
                                "username": proxy_user,
                                "password": proxy_pass,
                            }
                        elif len(parts) == 3:
                            parsed_proxy = {"server": proxy}
                        else:
                            self.logger.warning(f"Browser {index}: Invalid proxy format: {proxy}")

                    if parsed_proxy:
                        context_options["proxy"] = parsed_proxy
                        if self.debug:
                            self.logger.debug(f"Browser {index}: Creating context with proxy")
                    else:
                        proxy = None
                        if self.debug:
                            self.logger.debug(f"Browser {index}: Fallback to context without proxy")
                elif self.debug:
                    self.logger.debug(f"Browser {index}: Creating context without proxy")

            context = await browser.new_context(**context_options)
            page = await context.new_page()

            await self.antishadow_inject(page)
            await self.block_rendering(page)

            await page.add_init_script(
                """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });

            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
            };
            """
            )

            if self.pool_manager.browser_type in ["chromium", "chrome", "msedge"]:
                await page.set_viewport_size({"width": 500, "height": 100})
                if self.debug:
                    self.logger.debug(f"Browser {index}: Set viewport size to 500x100")

            if self.debug:
                self.logger.debug(
                    f"Browser {index}: Starting Turnstile solve for URL: {url} "
                    f"with Sitekey: {sitekey} | Action: {action} | Cdata: {cdata} | Proxy: {proxy}"
                )
                self.logger.debug(f"Browser {index}: Setting up optimized page loading with resource blocking")
                self.logger.debug(f"Browser {index}: Loading real website directly: {url}")

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self.unblock_rendering(page)

            if self.debug:
                self.logger.debug(f"Browser {index}: Injecting Turnstile widget directly into target site")

            await self.inject_captcha_directly(page, sitekey, action or "", cdata or "", index)
            await asyncio.sleep(3)

            locator = page.locator('input[name="cf-turnstile-response"]')
            max_attempts = 30
            click_count = 0
            max_clicks = 10

            for attempt in range(max_attempts):
                try:
                    try:
                        count = await locator.count()
                    except Exception as exc:
                        if self.debug:
                            self.logger.debug(f"Browser {index}: Locator count failed on attempt {attempt + 1}: {str(exc)}")
                        count = 0

                    if count == 0:
                        if self.debug and attempt % 5 == 0:
                            self.logger.debug(f"Browser {index}: No token elements found on attempt {attempt + 1}")
                    elif count == 1:
                        try:
                            token = await locator.input_value(timeout=500)
                            if token:
                                elapsed_time = round(time.time() - start_time, 3)
                                self.logger.success(
                                    f"Browser {index}: Successfully solved captcha - "
                                    f"{self.colors.get('MAGENTA')}{token[:10]}{self.colors.get('RESET')} in "
                                    f"{self.colors.get('GREEN')}{elapsed_time}{self.colors.get('RESET')} Seconds"
                                )
                                await self.repository.save_token(task_id, token=token, elapsed_time=elapsed_time)
                                return
                        except Exception as exc:
                            if self.debug:
                                self.logger.debug(f"Browser {index}: Single token element check failed: {str(exc)}")
                    else:
                        if self.debug:
                            self.logger.debug(f"Browser {index}: Found {count} token elements, checking all")

                        for element_index in range(count):
                            try:
                                element_token = await locator.nth(element_index).input_value(timeout=500)
                                if element_token:
                                    elapsed_time = round(time.time() - start_time, 3)
                                    self.logger.success(
                                        f"Browser {index}: Successfully solved captcha - "
                                        f"{self.colors.get('MAGENTA')}{element_token[:10]}{self.colors.get('RESET')} in "
                                        f"{self.colors.get('GREEN')}{elapsed_time}{self.colors.get('RESET')} Seconds"
                                    )
                                    await self.repository.save_token(task_id, token=element_token, elapsed_time=elapsed_time)
                                    return
                            except Exception as exc:
                                if self.debug:
                                    self.logger.debug(f"Browser {index}: Token element {element_index} check failed: {str(exc)}")
                                continue

                    if attempt > 2 and attempt % 3 == 0 and click_count < max_clicks:
                        click_success = await self.try_click_strategies(page, index)
                        click_count += 1
                        if click_success and self.debug:
                            self.logger.debug(f"Browser {index}: Click successful (click #{click_count}/{max_clicks})")
                        elif not click_success and self.debug:
                            self.logger.debug(
                                f"Browser {index}: All click strategies failed on attempt {attempt + 1} "
                                f"(click #{click_count}/{max_clicks})"
                            )

                    wait_time = min(0.5 + (attempt * 0.05), 2.0)
                    await asyncio.sleep(wait_time)

                    if self.debug and attempt % 5 == 0:
                        self.logger.debug(
                            f"Browser {index}: Attempt {attempt + 1}/{max_attempts} - "
                            f"Waiting for token (clicks: {click_count}/{max_clicks})"
                        )
                except Exception as exc:
                    if self.debug:
                        self.logger.debug(f"Browser {index}: Attempt {attempt + 1} error: {str(exc)}")
                    continue

            elapsed_time = round(time.time() - start_time, 3)
            await self.repository.save_failure(task_id, elapsed_time=elapsed_time)
            if self.debug:
                self.logger.error(
                    f"Browser {index}: Error solving Turnstile in "
                    f"{self.colors.get('RED')}{elapsed_time}{self.colors.get('RESET')} Seconds"
                )
        except Exception as exc:
            elapsed_time = round(time.time() - start_time, 3)
            await self.repository.save_failure(task_id, elapsed_time=elapsed_time)
            if self.debug:
                self.logger.error(f"Browser {index}: Error solving Turnstile: {str(exc)}")
        finally:
            if self.debug:
                self.logger.debug(f"Browser {index}: Closing browser context and cleaning up")

            if context is not None:
                try:
                    await context.close()
                    if self.debug:
                        self.logger.debug(f"Browser {index}: Context closed successfully")
                except Exception as exc:
                    if self.debug:
                        self.logger.warning(f"Browser {index}: Error closing context: {str(exc)}")

            try:
                await self.pool_manager.return_or_replace_browser(index=index, browser=browser, browser_config=browser_config)
            except Exception as exc:
                if self.debug:
                    self.logger.warning(f"Browser {index}: Error returning browser to pool: {str(exc)}")
