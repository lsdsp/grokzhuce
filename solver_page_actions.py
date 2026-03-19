class TurnstilePageActions:
    def __init__(self, *, debug: bool, logger):
        self.debug = debug
        self.logger = logger

    async def antishadow_inject(self, page):
        await page.add_init_script(
            """
          (function() {
            const originalAttachShadow = Element.prototype.attachShadow;
            Element.prototype.attachShadow = function(init) {
              const shadow = originalAttachShadow.call(this, init);
              if (init.mode === 'closed') {
                window.__lastClosedShadowRoot = shadow;
              }
              return shadow;
            };
          })();
        """
        )

    async def optimized_route_handler(self, route):
        url = route.request.url
        resource_type = route.request.resource_type
        allowed_types = {"document", "script", "xhr", "fetch"}
        allowed_domains = [
            "challenges.cloudflare.com",
            "static.cloudflareinsights.com",
            "cloudflare.com",
        ]

        if resource_type in allowed_types:
            await route.continue_()
        elif any(domain in url for domain in allowed_domains):
            await route.continue_()
        else:
            await route.abort()

    async def block_rendering(self, page):
        await page.route("**/*", self.optimized_route_handler)

    async def unblock_rendering(self, page):
        await page.unroute("**/*", self.optimized_route_handler)

    async def find_and_click_checkbox(self, page, index: int):
        try:
            iframe_selectors = [
                'iframe[src*="challenges.cloudflare.com"]',
                'iframe[src*="turnstile"]',
                'iframe[title*="widget"]',
            ]
            iframe_locator = None
            for selector in iframe_selectors:
                try:
                    test_locator = page.locator(selector).first
                    try:
                        iframe_count = await test_locator.count()
                    except Exception:
                        iframe_count = 0
                    if iframe_count > 0:
                        iframe_locator = test_locator
                        if self.debug:
                            self.logger.debug(f"Browser {index}: Found Turnstile iframe with selector: {selector}")
                        break
                except Exception as exc:
                    if self.debug:
                        self.logger.debug(f"Browser {index}: Iframe selector '{selector}' failed: {str(exc)}")
                    continue

            if iframe_locator:
                try:
                    iframe_element = await iframe_locator.element_handle()
                    frame = await iframe_element.content_frame()
                    if frame:
                        checkbox_selectors = [
                            'input[type="checkbox"]',
                            '.cb-lb input[type="checkbox"]',
                            'label input[type="checkbox"]',
                        ]
                        for selector in checkbox_selectors:
                            try:
                                checkbox = frame.locator(selector).first
                                await checkbox.click(timeout=2000)
                                if self.debug:
                                    self.logger.debug(
                                        f"Browser {index}: Successfully clicked checkbox in iframe with selector '{selector}'"
                                    )
                                return True
                            except Exception as click_exc:
                                if self.debug:
                                    self.logger.debug(
                                        f"Browser {index}: Direct checkbox click failed for '{selector}': {str(click_exc)}"
                                    )
                                continue
                        try:
                            if self.debug:
                                self.logger.debug(f"Browser {index}: Trying to click iframe directly as fallback")
                            await iframe_locator.click(timeout=1000)
                            return True
                        except Exception as exc:
                            if self.debug:
                                self.logger.debug(f"Browser {index}: Iframe direct click failed: {str(exc)}")
                except Exception as exc:
                    if self.debug:
                        self.logger.debug(f"Browser {index}: Failed to access iframe content: {str(exc)}")
        except Exception as exc:
            if self.debug:
                self.logger.debug(f"Browser {index}: General iframe search failed: {str(exc)}")
        return False

    async def safe_click(self, page, selector: str, index: int):
        try:
            locator = page.locator(selector).first
            await locator.click(timeout=1000)
            return True
        except Exception as exc:
            if self.debug and "Can't query n-th element" not in str(exc):
                self.logger.debug(f"Browser {index}: Safe click failed for '{selector}': {str(exc)}")
            return False

    async def try_click_strategies(self, page, index: int):
        strategies = [
            ("checkbox_click", lambda: self.find_and_click_checkbox(page, index)),
            ("direct_widget", lambda: self.safe_click(page, ".cf-turnstile", index)),
            ("iframe_click", lambda: self.safe_click(page, 'iframe[src*="turnstile"]', index)),
            ("js_click", lambda: page.evaluate("document.querySelector('.cf-turnstile')?.click()")),
            ("sitekey_attr", lambda: self.safe_click(page, "[data-sitekey]", index)),
            ("any_turnstile", lambda: self.safe_click(page, '*[class*="turnstile"]', index)),
            ("xpath_click", lambda: self.safe_click(page, "//div[@class='cf-turnstile']", index)),
        ]
        for strategy_name, strategy_func in strategies:
            try:
                result = await strategy_func()
                if result is True or result is None:
                    if self.debug:
                        self.logger.debug(f"Browser {index}: Click strategy '{strategy_name}' succeeded")
                    return True
            except Exception as exc:
                if self.debug:
                    self.logger.debug(f"Browser {index}: Click strategy '{strategy_name}' failed: {str(exc)}")
                continue
        return False

    async def inject_captcha_directly(self, page, websiteKey: str, action: str = "", cdata: str = "", index: int = 0):
        script = f"""
        document.querySelectorAll('.cf-turnstile').forEach(el => el.remove());
        document.querySelectorAll('[data-sitekey]').forEach(el => el.remove());
        const captchaDiv = document.createElement('div');
        captchaDiv.className = 'cf-turnstile';
        captchaDiv.setAttribute('data-sitekey', '{websiteKey}');
        captchaDiv.setAttribute('data-callback', 'onTurnstileCallback');
        {f'captchaDiv.setAttribute("data-action", "{action}");' if action else ''}
        {f'captchaDiv.setAttribute("data-cdata", "{cdata}");' if cdata else ''}
        captchaDiv.style.position = 'fixed';
        captchaDiv.style.top = '20px';
        captchaDiv.style.left = '20px';
        captchaDiv.style.zIndex = '9999';
        captchaDiv.style.backgroundColor = 'white';
        captchaDiv.style.padding = '15px';
        captchaDiv.style.border = '2px solid #0f79af';
        captchaDiv.style.borderRadius = '8px';
        captchaDiv.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.3)';
        document.body.appendChild(captchaDiv);
        const loadTurnstile = () => {{
            const script = document.createElement('script');
            script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
            script.async = true;
            script.defer = true;
            script.onload = function() {{
                console.log('Turnstile script loaded');
                setTimeout(() => {{
                    if (window.turnstile && window.turnstile.render) {{
                        try {{
                            window.turnstile.render(captchaDiv, {{
                                sitekey: '{websiteKey}',
                                {f'action: "{action}",' if action else ''}
                                {f'cdata: "{cdata}",' if cdata else ''}
                                callback: function(token) {{
                                    console.log('Turnstile solved with token:', token);
                                    let tokenInput = document.querySelector('input[name="cf-turnstile-response"]');
                                    if (!tokenInput) {{
                                        tokenInput = document.createElement('input');
                                        tokenInput.type = 'hidden';
                                        tokenInput.name = 'cf-turnstile-response';
                                        document.body.appendChild(tokenInput);
                                    }}
                                    tokenInput.value = token;
                                }},
                                'error-callback': function(error) {{
                                    console.log('Turnstile error:', error);
                                }}
                            }});
                        }} catch (e) {{
                            console.log('Turnstile render error:', e);
                        }}
                    }} else {{
                        console.log('Turnstile API not available');
                    }}
                }}, 1000);
            }};
            script.onerror = function() {{
                console.log('Failed to load Turnstile script');
            }};
            document.head.appendChild(script);
        }};
        if (window.turnstile) {{
            console.log('Turnstile already loaded, rendering immediately');
            try {{
                window.turnstile.render(captchaDiv, {{
                    sitekey: '{websiteKey}',
                    {f'action: "{action}",' if action else ''}
                    {f'cdata: "{cdata}",' if cdata else ''}
                    callback: function(token) {{
                        console.log('Turnstile solved with token:', token);
                        let tokenInput = document.querySelector('input[name="cf-turnstile-response"]');
                        if (!tokenInput) {{
                            tokenInput = document.createElement('input');
                            tokenInput.type = 'hidden';
                            tokenInput.name = 'cf-turnstile-response';
                            document.body.appendChild(tokenInput);
                        }}
                        tokenInput.value = token;
                    }},
                    'error-callback': function(error) {{
                        console.log('Turnstile error:', error);
                    }}
                }});
            }} catch (e) {{
                console.log('Immediate render error:', e);
                loadTurnstile();
            }}
        }} else {{
            loadTurnstile();
        }}
        window.onTurnstileCallback = function(token) {{
            console.log('Global turnstile callback executed:', token);
        }};
        """
        await page.evaluate(script)
        if self.debug:
            self.logger.debug(f"Browser {index}: Injected CAPTCHA directly into website with sitekey: {websiteKey}")
