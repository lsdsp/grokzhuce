import asyncio
import os
import random
import re
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
        event_logger,
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
        self.event_logger = event_logger
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
        self._emit_event(
            "info",
            "solver_enqueue",
            "captcha task enqueued",
            task_id=task_id,
            error_type="none",
            sitekey=sitekey,
            action=action,
        )
        asyncio.create_task(self.solve_turnstile(task_id=task_id, url=url, sitekey=sitekey, action=action, cdata=cdata))
        return task_id

    async def get_result_payload(self, task_id: str):
        result = await self.repository.load(task_id)
        return self.repository.build_result_payload(result)

    @staticmethod
    def _normalize_failure_reason(value) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        return text or "unknown_failure"

    def _emit_event(self, level: str, stage: str, message: str, **fields):
        if self.event_logger is None:
            return
        clean_fields = {key: value for key, value in fields.items() if value not in (None, "")}
        self.event_logger.event(level, stage, message, **clean_fields)

    async def _save_failure(self, task_id: str, *, elapsed_time: float, failed_stage: str, failure_reason, browser_index=None, proxy=None, browser_config=None):
        normalized_reason = self._normalize_failure_reason(failure_reason)
        diagnostics = {
            "failure_reason": normalized_reason,
            "failed_stage": failed_stage,
            "browser_index": browser_index,
            "proxy": proxy,
        }
        if isinstance(browser_config, dict):
            diagnostics["browser_name"] = browser_config.get("browser_name")
            diagnostics["browser_version"] = browser_config.get("browser_version")
        await self.repository.save_failure(task_id, elapsed_time=elapsed_time, **diagnostics)
        self._emit_event(
            "error",
            "solver_failure",
            "captcha solve failed",
            task_id=task_id,
            browser_index=browser_index,
            failed_stage=failed_stage,
            failure_reason=normalized_reason,
            proxy=proxy,
            latency_ms=int(elapsed_time * 1000),
            error_type="captcha",
            browser_name=diagnostics.get("browser_name"),
            browser_version=diagnostics.get("browser_version"),
        )

    async def solve_turnstile(self, task_id: str, url: str, sitekey: str, action: Optional[str] = None, cdata: Optional[str] = None):
        proxy = None
        context = None
        start_time = time.time()
        current_stage = "acquire_browser"

        index, browser, browser_config = await self.pool_manager.browser_pool.get()

        try:
            try:
                current_stage = "check_browser_connection"
                if hasattr(browser, "is_connected") and not browser.is_connected():
                    if self.debug:
                        self.logger.warning(f"Browser {index}: Browser disconnected, recreating")
                    current_stage = "replace_browser"
                    replacement = await self.pool_manager.spawn_browser_for_config(index=index, config=browser_config)
                    if not replacement:
                        await self._save_failure(
                            task_id,
                            elapsed_time=0,
                            failed_stage=current_stage,
                            failure_reason="replacement_browser_unavailable",
                            browser_index=index,
                            browser_config=browser_config,
                        )
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
                current_stage = "load_proxy"
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

            current_stage = "create_context"
            context = await browser.new_context(**context_options)
            current_stage = "create_page"
            page = await context.new_page()

            current_stage = "inject_antishadow"
            await self.antishadow_inject(page)
            current_stage = "block_rendering"
            await self.block_rendering(page)

            current_stage = "inject_init_script"
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

            current_stage = "navigate"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            current_stage = "unblock_rendering"
            await self.unblock_rendering(page)

            if self.debug:
                self.logger.debug(f"Browser {index}: Injecting Turnstile widget directly into target site")

            current_stage = "inject_captcha"
            await self.inject_captcha_directly(page, sitekey, action or "", cdata or "", index)
            current_stage = "wait_after_inject"
            await asyncio.sleep(3)

            locator = page.locator('input[name="cf-turnstile-response"]')
            max_attempts = 30
            click_count = 0
            max_clicks = 10

            current_stage = "poll_for_token"
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
                                self._emit_event(
                                    "info",
                                    "solver_success",
                                    "captcha solved",
                                    task_id=task_id,
                                    browser_index=index,
                                    latency_ms=int(elapsed_time * 1000),
                                    error_type="none",
                                    browser_name=browser_config.get("browser_name"),
                                    browser_version=browser_config.get("browser_version"),
                                )
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
                                    self._emit_event(
                                        "info",
                                        "solver_success",
                                        "captcha solved",
                                        task_id=task_id,
                                        browser_index=index,
                                        latency_ms=int(elapsed_time * 1000),
                                        error_type="none",
                                        browser_name=browser_config.get("browser_name"),
                                        browser_version=browser_config.get("browser_version"),
                                    )
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
            await self._save_failure(
                task_id,
                elapsed_time=elapsed_time,
                failed_stage=current_stage,
                failure_reason="token_not_found",
                browser_index=index,
                proxy=proxy,
                browser_config=browser_config,
            )
            if self.debug:
                self.logger.error(
                    f"Browser {index}: Error solving Turnstile in "
                    f"{self.colors.get('RED')}{elapsed_time}{self.colors.get('RESET')} Seconds"
                )
        except Exception as exc:
            elapsed_time = round(time.time() - start_time, 3)
            await self._save_failure(
                task_id,
                elapsed_time=elapsed_time,
                failed_stage=current_stage,
                failure_reason=exc,
                browser_index=index,
                proxy=proxy,
                browser_config=browser_config,
            )
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
