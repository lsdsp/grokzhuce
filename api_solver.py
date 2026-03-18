import os
import sys
import time
import logging
import asyncio
from typing import Optional
import argparse
from quart import Quart, request, jsonify
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich import box

from solver_browser_pool import BrowserPoolManager
from solver_result_repository import SolverResultRepository
from solver_task_service import TurnstileTaskService



COLORS = {
    'MAGENTA': '\033[35m',
    'BLUE': '\033[34m',
    'GREEN': '\033[32m',
    'YELLOW': '\033[33m',
    'RED': '\033[31m',
    'RESET': '\033[0m',
}


class CustomLogger(logging.Logger):
    @staticmethod
    def format_message(level, color, message):
        timestamp = time.strftime('%H:%M:%S')
        return f"[{timestamp}] [{COLORS.get(color)}{level}{COLORS.get('RESET')}] -> {message}"

    def debug(self, message, *args, **kwargs):
        super().debug(self.format_message('DEBUG', 'MAGENTA', message), *args, **kwargs)

    def info(self, message, *args, **kwargs):
        super().info(self.format_message('INFO', 'BLUE', message), *args, **kwargs)

    def success(self, message, *args, **kwargs):
        super().info(self.format_message('SUCCESS', 'GREEN', message), *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        super().warning(self.format_message('WARNING', 'YELLOW', message), *args, **kwargs)

    def error(self, message, *args, **kwargs):
        super().error(self.format_message('ERROR', 'RED', message), *args, **kwargs)


logging.setLoggerClass(CustomLogger)
logger: CustomLogger = logging.getLogger("TurnstileAPIServer")  # type: ignore
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
logger.addHandler(handler)


class TurnstileAPIServer:

    def __init__(self, headless: bool, useragent: Optional[str], debug: bool, browser_type: str, thread: int, proxy_support: bool, use_random_config: bool = False, browser_name: Optional[str] = None, browser_version: Optional[str] = None):
        self.app = Quart(__name__)
        self.debug = debug
        self.browser_type = browser_type
        self.headless = headless
        self.thread_count = thread
        self.proxy_support = proxy_support
        self.use_random_config = use_random_config
        self.browser_name = browser_name
        self.browser_version = browser_version
        self.console = Console()
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.repository = SolverResultRepository()
        self.pool_manager = BrowserPoolManager(
            headless=headless,
            browser_type=browser_type,
            thread_count=thread,
            debug=debug,
            proxy_support=proxy_support,
            useragent=useragent,
            use_random_config=use_random_config,
            browser_name=browser_name,
            browser_version=browser_version,
            base_dir=self.base_dir,
            logger=logger,
        )
        self.browser_pool = self.pool_manager.browser_pool
        self.task_service = TurnstileTaskService(
            pool_manager=self.pool_manager,
            repository=self.repository,
            logger=logger,
            colors=COLORS,
            debug=debug,
            antishadow_inject=self._antishadow_inject,
            block_rendering=self._block_rendering,
            unblock_rendering=self._unblock_rendering,
            inject_captcha_directly=self._inject_captcha_directly,
            try_click_strategies=self._try_click_strategies,
        )

        self._setup_routes()

    def display_welcome(self):
        """Displays welcome screen with logo."""
        self.console.clear()
        
        combined_text = Text()
        combined_text.append("\nChannel: ", style="bold white")
        combined_text.append("https://t.me/D3_vin", style="cyan")
        combined_text.append("\nChat: ", style="bold white")
        combined_text.append("https://t.me/D3vin_chat", style="cyan")
        combined_text.append("\nGitHub: ", style="bold white")
        combined_text.append("https://github.com/D3-vin", style="cyan")
        combined_text.append("\nVersion: ", style="bold white")
        combined_text.append("1.2a", style="green")
        combined_text.append("\n")

        info_panel = Panel(
            Align.left(combined_text),
            title="[bold blue]Turnstile Solver[/bold blue]",
            subtitle="[bold magenta]Dev by D3vin[/bold magenta]",
            box=box.ROUNDED,
            border_style="bright_blue",
            padding=(0, 1),
            width=50
        )

        self.console.print(info_panel)
        self.console.print()




    def _setup_routes(self) -> None:
        """Set up the application routes."""
        self.app.before_serving(self._startup)
        self.app.route('/turnstile', methods=['GET'])(self.process_turnstile)
        self.app.route('/result', methods=['GET'])(self.get_result)
        self.app.route('/')(self.index)
        

    async def _startup(self) -> None:
        """Initialize the browser and page pool on startup."""
        self.display_welcome()
        logger.info("Starting browser initialization")
        try:
            await self.repository.init()
            await self._initialize_browser()
            
            # Запускаем периодическую очистку старых результатов
            asyncio.create_task(self._periodic_cleanup())
            
        except Exception as e:
            logger.error(f"Failed to initialize browser: {str(e)}")
            raise

    async def _initialize_browser(self) -> None:
        """Initialize the browser and create the page pool."""
        await self.pool_manager.initialize()
        self.browser_pool = self.pool_manager.browser_pool

    async def _spawn_browser_for_config(self, index: int, config: dict):
        """Create a replacement browser using an existing config."""
        return await self.pool_manager.spawn_browser_for_config(index=index, config=config)

    async def _return_or_replace_browser(self, index: int, browser, browser_config: dict):
        """Return browser to pool; when disconnected, try to replace it to avoid pool depletion."""
        await self.pool_manager.return_or_replace_browser(index=index, browser=browser, browser_config=browser_config)

    async def _periodic_cleanup(self):
        """Periodic cleanup of old results every hour"""
        while True:
            try:
                await asyncio.sleep(3600)
                deleted_count = await self.repository.cleanup(days_old=7)
                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} old results")
            except Exception as e:
                logger.error(f"Error during periodic cleanup: {e}")

    async def _antishadow_inject(self, page):
        await page.add_init_script("""
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
        """)



    async def _optimized_route_handler(self, route):
        """Оптимизированный обработчик маршрутов для экономии ресурсов."""
        url = route.request.url
        resource_type = route.request.resource_type

        allowed_types = {'document', 'script', 'xhr', 'fetch'}

        allowed_domains = [
            'challenges.cloudflare.com',
            'static.cloudflareinsights.com',
            'cloudflare.com'
        ]
        
        if resource_type in allowed_types:
            await route.continue_()
        elif any(domain in url for domain in allowed_domains):
            await route.continue_() 
        else:
            await route.abort()

    async def _block_rendering(self, page):
        """Блокировка рендеринга для экономии ресурсов"""
        await page.route("**/*", self._optimized_route_handler)

    async def _unblock_rendering(self, page):
        """Разблокировка рендеринга"""
        await page.unroute("**/*", self._optimized_route_handler)

    async def _find_turnstile_elements(self, page, index: int):
        """Умная проверка всех возможных Turnstile элементов"""
        selectors = [
            '.cf-turnstile',
            '[data-sitekey]',
            'iframe[src*="turnstile"]',
            'iframe[title*="widget"]',
            'div[id*="turnstile"]',
            'div[class*="turnstile"]'
        ]
        
        elements = []
        for selector in selectors:
            try:
                # Безопасная проверка count()
                try:
                    count = await page.locator(selector).count()
                except Exception:
                    # Если count() дает ошибку, пропускаем этот селектор
                    continue
                    
                if count > 0:
                    elements.append((selector, count))
                    if self.debug:
                        logger.debug(f"Browser {index}: Found {count} elements with selector '{selector}'")
            except Exception as e:
                if self.debug:
                    logger.debug(f"Browser {index}: Selector '{selector}' failed: {str(e)}")
                continue
        
        return elements

    async def _find_and_click_checkbox(self, page, index: int):
        """Найти и кликнуть по чекбоксу Turnstile CAPTCHA внутри iframe"""
        try:
            # Пробуем разные селекторы iframe с защитой от ошибок
            iframe_selectors = [
                'iframe[src*="challenges.cloudflare.com"]',
                'iframe[src*="turnstile"]',
                'iframe[title*="widget"]'
            ]
            
            iframe_locator = None
            for selector in iframe_selectors:
                try:
                    test_locator = page.locator(selector).first
                    # Безопасная проверка count для iframe
                    try:
                        iframe_count = await test_locator.count()
                    except Exception:
                        iframe_count = 0
                        
                    if iframe_count > 0:
                        iframe_locator = test_locator
                        if self.debug:
                            logger.debug(f"Browser {index}: Found Turnstile iframe with selector: {selector}")
                        break
                except Exception as e:
                    if self.debug:
                        logger.debug(f"Browser {index}: Iframe selector '{selector}' failed: {str(e)}")
                    continue
            
            if iframe_locator:
                try:
                    # Получаем frame из iframe
                    iframe_element = await iframe_locator.element_handle()
                    frame = await iframe_element.content_frame()
                    
                    if frame:
                        # Ищем чекбокс внутри iframe
                        checkbox_selectors = [
                            'input[type="checkbox"]',
                            '.cb-lb input[type="checkbox"]',
                            'label input[type="checkbox"]'
                        ]
                        
                        for selector in checkbox_selectors:
                            try:
                                # Полностью избегаем locator.count() в iframe - используем альтернативный подход
                                try:
                                    # Пробуем кликнуть напрямую без count проверки
                                    checkbox = frame.locator(selector).first
                                    await checkbox.click(timeout=2000)
                                    if self.debug:
                                        logger.debug(f"Browser {index}: Successfully clicked checkbox in iframe with selector '{selector}'")
                                    return True
                                except Exception as click_e:
                                    # Если прямой клик не сработал, записываем в debug но не падаем
                                    if self.debug:
                                        logger.debug(f"Browser {index}: Direct checkbox click failed for '{selector}': {str(click_e)}")
                                    continue
                            except Exception as e:
                                if self.debug:
                                    logger.debug(f"Browser {index}: Iframe checkbox selector '{selector}' failed: {str(e)}")
                                continue
                    
                        # Если нашли iframe, но не смогли кликнуть чекбокс, пробуем клик по iframe
                        try:
                            if self.debug:
                                logger.debug(f"Browser {index}: Trying to click iframe directly as fallback")
                            await iframe_locator.click(timeout=1000)
                            return True
                        except Exception as e:
                            if self.debug:
                                logger.debug(f"Browser {index}: Iframe direct click failed: {str(e)}")
                
                except Exception as e:
                    if self.debug:
                        logger.debug(f"Browser {index}: Failed to access iframe content: {str(e)}")
            
        except Exception as e:
            if self.debug:
                logger.debug(f"Browser {index}: General iframe search failed: {str(e)}")
        
        return False

    async def _try_click_strategies(self, page, index: int):
        strategies = [
            ('checkbox_click', lambda: self._find_and_click_checkbox(page, index)),
            ('direct_widget', lambda: self._safe_click(page, '.cf-turnstile', index)),
            ('iframe_click', lambda: self._safe_click(page, 'iframe[src*="turnstile"]', index)),
            ('js_click', lambda: page.evaluate("document.querySelector('.cf-turnstile')?.click()")),
            ('sitekey_attr', lambda: self._safe_click(page, '[data-sitekey]', index)),
            ('any_turnstile', lambda: self._safe_click(page, '*[class*="turnstile"]', index)),
            ('xpath_click', lambda: self._safe_click(page, "//div[@class='cf-turnstile']", index))
        ]
        
        for strategy_name, strategy_func in strategies:
            try:
                result = await strategy_func()
                if result is True or result is None:  # None означает успех для большинства стратегий
                    if self.debug:
                        logger.debug(f"Browser {index}: Click strategy '{strategy_name}' succeeded")
                    return True
            except Exception as e:
                if self.debug:
                    logger.debug(f"Browser {index}: Click strategy '{strategy_name}' failed: {str(e)}")
                continue
        
        return False

    async def _safe_click(self, page, selector: str, index: int):
        """Полностью безопасный клик с максимальной защитой от ошибок"""
        try:
            # Пробуем кликнуть напрямую без count() проверки
            locator = page.locator(selector).first
            await locator.click(timeout=1000)
            return True
        except Exception as e:
            # Логируем ошибку только в debug режиме
            if self.debug and "Can't query n-th element" not in str(e):
                logger.debug(f"Browser {index}: Safe click failed for '{selector}': {str(e)}")
            return False

    async def _inject_captcha_directly(self, page, websiteKey: str, action: str = '', cdata: str = '', index: int = 0):
        """Inject CAPTCHA directly into the target website"""
        script = f"""
        // Remove any existing turnstile widgets first
        document.querySelectorAll('.cf-turnstile').forEach(el => el.remove());
        document.querySelectorAll('[data-sitekey]').forEach(el => el.remove());
        
        // Create turnstile widget directly on the page
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
        
        // Add to body immediately
        document.body.appendChild(captchaDiv);
        
        // Load Turnstile script and render widget
        const loadTurnstile = () => {{
            const script = document.createElement('script');
            script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
            script.async = true;
            script.defer = true;
            script.onload = function() {{
                console.log('Turnstile script loaded');
                // Wait a bit for script to initialize
                setTimeout(() => {{
                    if (window.turnstile && window.turnstile.render) {{
                        try {{
                            window.turnstile.render(captchaDiv, {{
                                sitekey: '{websiteKey}',
                                {f'action: "{action}",' if action else ''}
                                {f'cdata: "{cdata}",' if cdata else ''}
                                callback: function(token) {{
                                    console.log('Turnstile solved with token:', token);
                                    // Create hidden input for token
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
        
        // Check if Turnstile is already loaded
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
        
        // Setup global callback
        window.onTurnstileCallback = function(token) {{
            console.log('Global turnstile callback executed:', token);
        }};
        """

        await page.evaluate(script)
        if self.debug:
            logger.debug(f"Browser {index}: Injected CAPTCHA directly into website with sitekey: {websiteKey}")

    async def _solve_turnstile(self, task_id: str, url: str, sitekey: str, action: Optional[str] = None, cdata: Optional[str] = None):
        """Solve the Turnstile challenge."""
        await self.task_service.solve_turnstile(task_id=task_id, url=url, sitekey=sitekey, action=action, cdata=cdata)






    async def process_turnstile(self):
        """Handle the /turnstile endpoint requests."""
        url = request.args.get('url')
        sitekey = request.args.get('sitekey')
        action = request.args.get('action')
        cdata = request.args.get('cdata')

        if not url or not sitekey:
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_WRONG_PAGEURL",
                "errorDescription": "Both 'url' and 'sitekey' are required"
            }), 200

        try:
            task_id = await self.task_service.enqueue_task(
                url=url,
                sitekey=sitekey,
                action=action,
                cdata=cdata,
            )

            if self.debug:
                logger.debug(f"Request completed with taskid {task_id}.")
            return jsonify({
                "errorId": 0,
                "taskId": task_id
            }), 200
        except Exception as e:
            logger.error(f"Unexpected error processing request: {str(e)}")
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_UNKNOWN",
                "errorDescription": str(e)
            }), 200

    async def get_result(self):
        """Return solved data"""
        task_id = request.args.get('id')

        if not task_id:
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_WRONG_CAPTCHA_ID",
                "errorDescription": "Invalid task ID/Request parameter"
            }), 200

        payload = await self.task_service.get_result_payload(task_id)
        return jsonify(payload), 200

    

    @staticmethod
    async def index():
        """Serve the API documentation page."""
        return """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Turnstile Solver API</title>
                <script src="https://cdn.tailwindcss.com"></script>
            </head>
            <body class="bg-gray-900 text-gray-200 min-h-screen flex items-center justify-center">
                <div class="bg-gray-800 p-8 rounded-lg shadow-md max-w-2xl w-full border border-red-500">
                    <h1 class="text-3xl font-bold mb-6 text-center text-red-500">Welcome to Turnstile Solver API</h1>

                    <p class="mb-4 text-gray-300">To use the turnstile service, send a GET request to 
                       <code class="bg-red-700 text-white px-2 py-1 rounded">/turnstile</code> with the following query parameters:</p>

                    <ul class="list-disc pl-6 mb-6 text-gray-300">
                        <li><strong>url</strong>: The URL where Turnstile is to be validated</li>
                        <li><strong>sitekey</strong>: The site key for Turnstile</li>
                    </ul>

                    <div class="bg-gray-700 p-4 rounded-lg mb-6 border border-red-500">
                        <p class="font-semibold mb-2 text-red-400">Example usage:</p>
                        <code class="text-sm break-all text-red-300">/turnstile?url=https://example.com&sitekey=sitekey</code>
                    </div>


                    <div class="bg-gray-700 p-4 rounded-lg mb-6">
                        <p class="text-gray-200 font-semibold mb-3">📢 Connect with Us</p>
                        <div class="space-y-2 text-sm">
                            <p class="text-gray-300">
                                📢 <strong>Channel:</strong> 
                                <a href="https://t.me/D3_vin" class="text-red-300 hover:underline">https://t.me/D3_vin</a> 
                                - Latest updates and releases
                            </p>
                            <p class="text-gray-300">
                                💬 <strong>Chat:</strong> 
                                <a href="https://t.me/D3vin_chat" class="text-red-300 hover:underline">https://t.me/D3vin_chat</a> 
                                - Community support and discussions
                            </p>
                            <p class="text-gray-300">
                                📁 <strong>GitHub:</strong> 
                                <a href="https://github.com/D3-vin" class="text-red-300 hover:underline">https://github.com/D3-vin</a> 
                                - Source code and development
                            </p>
                        </div>
                    </div>
                </div>
            </body>
            </html>
        """


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Turnstile API Server")

    parser.add_argument('--no-headless', action='store_true', help='Run the browser with GUI (disable headless mode). By default, headless mode is enabled.')
    parser.add_argument('--useragent', type=str, help='User-Agent string (if not specified, random configuration is used)')
    parser.add_argument('--debug', action='store_true', help='Enable or disable debug mode for additional logging and troubleshooting information (default: False)')
    parser.add_argument('--browser_type', type=str, default='chromium', help='Specify the browser type for the solver. Supported options: chromium, chrome, msedge, camoufox (default: chromium)')
    parser.add_argument('--thread', type=int, default=4, help='Set the number of browser threads to use for multi-threaded mode. Increasing this will speed up execution but requires more resources (default: 4)')
    parser.add_argument('--proxy', action='store_true', help='Enable proxy support for the solver (Default: False)')
    parser.add_argument('--random', action='store_true', help='Use random User-Agent and Sec-CH-UA configuration from pool')
    parser.add_argument('--browser', type=str, help='Specify browser name to use (e.g., chrome, firefox)')
    parser.add_argument('--version', type=str, help='Specify browser version to use (e.g., 139, 141)')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Specify the IP address where the API solver runs. (Default: 127.0.0.1)')
    parser.add_argument('--port', type=str, default='5072', help='Set the port for the API solver to listen on. (Default: 5072)')
    return parser.parse_args()


def create_app(headless: bool, useragent: str, debug: bool, browser_type: str, thread: int, proxy_support: bool, use_random_config: bool, browser_name: str, browser_version: str) -> Quart:
    server = TurnstileAPIServer(headless=headless, useragent=useragent, debug=debug, browser_type=browser_type, thread=thread, proxy_support=proxy_support, use_random_config=use_random_config, browser_name=browser_name, browser_version=browser_version)
    return server.app


if __name__ == '__main__':
    args = parse_args()
    browser_types = [
        'chromium',
        'chrome',
        'msedge',
        'camoufox',
    ]
    if args.browser_type not in browser_types:
        logger.error(f"Unknown browser type: {COLORS.get('RED')}{args.browser_type}{COLORS.get('RESET')} Available browser types: {browser_types}")
    else:
        app = create_app(
            headless=not args.no_headless, 
            debug=args.debug, 
            useragent=args.useragent, 
            browser_type=args.browser_type, 
            thread=args.thread, 
            proxy_support=args.proxy,
            use_random_config=args.random,
            browser_name=args.browser,
            browser_version=args.version
        )
        app.run(host=args.host, port=int(args.port))
