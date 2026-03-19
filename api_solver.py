import argparse

from grok_env import load_project_env
from solver_logging import COLORS, CustomLogger, get_solver_logger
from solver_server import TurnstileAPIServer


load_project_env()
logger = get_solver_logger()


def parse_args():
    parser = argparse.ArgumentParser(description="Turnstile API Server")

    parser.add_argument("--no-headless", action="store_true", help="Run the browser with GUI (disable headless mode). By default, headless mode is enabled.")
    parser.add_argument("--useragent", type=str, help="User-Agent string (if not specified, random configuration is used)")
    parser.add_argument("--debug", action="store_true", help="Enable or disable debug mode for additional logging and troubleshooting information (default: False)")
    parser.add_argument("--browser_type", type=str, default="chromium", help="Specify the browser type for the solver. Supported options: chromium, chrome, msedge, camoufox (default: chromium)")
    parser.add_argument("--thread", type=int, default=4, help="Set the number of browser threads to use for multi-threaded mode. Increasing this will speed up execution but requires more resources (default: 4)")
    parser.add_argument("--proxy", action="store_true", help="Enable proxy support for the solver (Default: False)")
    parser.add_argument("--random", action="store_true", help="Use random User-Agent and Sec-CH-UA configuration from pool")
    parser.add_argument("--browser", type=str, help="Specify browser name to use (e.g., chrome, firefox)")
    parser.add_argument("--version", type=str, help="Specify browser version to use (e.g., 139, 141)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Specify the IP address where the API solver runs. (Default: 127.0.0.1)")
    parser.add_argument("--port", type=str, default="5072", help="Set the port for the API solver to listen on. (Default: 5072)")
    return parser.parse_args()


def create_app(headless: bool, useragent: str, debug: bool, browser_type: str, thread: int, proxy_support: bool, use_random_config: bool, browser_name: str, browser_version: str):
    server = TurnstileAPIServer(
        headless=headless,
        useragent=useragent,
        debug=debug,
        browser_type=browser_type,
        thread=thread,
        proxy_support=proxy_support,
        use_random_config=use_random_config,
        browser_name=browser_name,
        browser_version=browser_version,
    )
    return server.app


if __name__ == "__main__":
    args = parse_args()
    browser_types = ["chromium", "chrome", "msedge", "camoufox"]
    if args.browser_type not in browser_types:
        logger.error(
            f"Unknown browser type: {COLORS.get('RED')}{args.browser_type}{COLORS.get('RESET')} Available browser types: {browser_types}"
        )
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
            browser_version=args.version,
        )
        app.run(host=args.host, port=int(args.port))
