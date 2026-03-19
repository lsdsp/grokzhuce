import asyncio
import os
from typing import Optional

from quart import Quart, jsonify, request
from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from solver_browser_pool import BrowserPoolManager
from solver_logging import COLORS, get_solver_event_logger, get_solver_logger
from solver_page_actions import TurnstilePageActions
from solver_result_repository import SolverResultRepository
from solver_task_service import TurnstileTaskService


logger = get_solver_logger()
event_logger = get_solver_event_logger()


class TurnstileAPIServer:
    def __init__(
        self,
        headless: bool,
        useragent: Optional[str],
        debug: bool,
        browser_type: str,
        thread: int,
        proxy_support: bool,
        use_random_config: bool = False,
        browser_name: Optional[str] = None,
        browser_version: Optional[str] = None,
        repository=None,
        page_actions=None,
    ):
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
        self.repository = repository or SolverResultRepository()
        self.page_actions = page_actions or TurnstilePageActions(debug=debug, logger=logger)
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
            event_logger=event_logger,
            colors=COLORS,
            debug=debug,
            antishadow_inject=self.page_actions.antishadow_inject,
            block_rendering=self.page_actions.block_rendering,
            unblock_rendering=self.page_actions.unblock_rendering,
            inject_captcha_directly=self.page_actions.inject_captcha_directly,
            try_click_strategies=self.page_actions.try_click_strategies,
        )

        self._setup_routes()

    def display_welcome(self):
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
            width=50,
        )

        self.console.print(info_panel)
        self.console.print()

    def _setup_routes(self) -> None:
        self.app.before_serving(self._startup)
        self.app.route("/turnstile", methods=["GET"])(self.process_turnstile)
        self.app.route("/result", methods=["GET"])(self.get_result)
        self.app.route("/")(self.index)

    async def _startup(self) -> None:
        self.display_welcome()
        logger.info("Starting browser initialization")
        try:
            await self.repository.init()
            await self._initialize_browser()
            asyncio.create_task(self._periodic_cleanup())
        except Exception as exc:
            logger.error(f"Failed to initialize browser: {str(exc)}")
            raise

    async def _initialize_browser(self) -> None:
        await self.pool_manager.initialize()
        self.browser_pool = self.pool_manager.browser_pool

    async def _spawn_browser_for_config(self, index: int, config: dict):
        return await self.pool_manager.spawn_browser_for_config(index=index, config=config)

    async def _return_or_replace_browser(self, index: int, browser, browser_config: dict):
        await self.pool_manager.return_or_replace_browser(index=index, browser=browser, browser_config=browser_config)

    async def _periodic_cleanup(self):
        while True:
            try:
                await asyncio.sleep(3600)
                deleted_count = await self.repository.cleanup(days_old=7)
                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} old results")
            except Exception as exc:
                logger.error(f"Error during periodic cleanup: {exc}")

    async def process_turnstile(self):
        url = request.args.get("url")
        sitekey = request.args.get("sitekey")
        action = request.args.get("action")
        cdata = request.args.get("cdata")

        if not url or not sitekey:
            return (
                jsonify(
                    {
                        "errorId": 1,
                        "errorCode": "ERROR_WRONG_PAGEURL",
                        "errorDescription": "Both 'url' and 'sitekey' are required",
                    }
                ),
                200,
            )

        try:
            task_id = await self.task_service.enqueue_task(
                url=url,
                sitekey=sitekey,
                action=action,
                cdata=cdata,
            )

            if self.debug:
                logger.debug(f"Request completed with taskid {task_id}.")
            return jsonify({"errorId": 0, "taskId": task_id}), 200
        except Exception as exc:
            logger.error(f"Unexpected error processing request: {str(exc)}")
            return (
                jsonify(
                    {
                        "errorId": 1,
                        "errorCode": "ERROR_UNKNOWN",
                        "errorDescription": str(exc),
                    }
                ),
                200,
            )

    async def get_result(self):
        task_id = request.args.get("id")

        if not task_id:
            return (
                jsonify(
                    {
                        "errorId": 1,
                        "errorCode": "ERROR_WRONG_CAPTCHA_ID",
                        "errorDescription": "Invalid task ID/Request parameter",
                    }
                ),
                200,
            )

        payload = await self.task_service.get_result_payload(task_id)
        return jsonify(payload), 200

    @staticmethod
    async def index():
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
