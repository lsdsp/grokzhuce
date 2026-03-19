import re
import time
from typing import Sequence
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests

from grok_config import DEFAULT_IMPERSONATE, DEFAULT_SITE_URL
from grok_runtime import ErrorType, RuntimeContext, StageResult


def extract_signup_bootstrap(*, html: str, js_bodies: Sequence[str], runtime: RuntimeContext) -> StageResult:
    normalized_html = html.replace('\\"', '"')

    site_key_match = re.search(r'sitekey":"(0x4[a-zA-Z0-9_-]+)"', normalized_html)
    if site_key_match:
        runtime.site_key = site_key_match.group(1)

    state_tree_match = re.search(r'next-router-state-tree":"([^"]+)"', normalized_html)
    if state_tree_match:
        runtime.state_tree = state_tree_match.group(1)

    for js_body in js_bodies:
        action_match = re.search(r"7f[a-fA-F0-9]{40}", js_body)
        if action_match:
            runtime.action_id = action_match.group(0)
            break

    if not runtime.action_id:
        return StageResult(False, "scan_bootstrap", ErrorType.PARSE, False, "未找到 Action ID")
    return StageResult(True, "scan_bootstrap")


def scan_signup_bootstrap(runtime: RuntimeContext, proxies, *, site_url: str = DEFAULT_SITE_URL) -> StageResult:
    started_at = time.perf_counter()
    try:
        with requests.Session(impersonate=DEFAULT_IMPERSONATE, proxies=proxies or None) as session:
            html = session.get(f"{site_url}/sign-up", timeout=30).text
            soup = BeautifulSoup(html, "html.parser")
            js_urls = [
                urljoin(f"{site_url}/sign-up", script["src"])
                for script in soup.find_all("script", src=True)
                if "_next/static" in script["src"]
            ]
            js_bodies = [session.get(js_url, timeout=30).text for js_url in js_urls]
        result = extract_signup_bootstrap(html=html, js_bodies=js_bodies, runtime=runtime)
        result.latency_ms = int((time.perf_counter() - started_at) * 1000)
        return result
    except Exception as exc:
        return StageResult(
            False,
            "scan_bootstrap",
            ErrorType.NETWORK,
            True,
            str(exc),
            latency_ms=int((time.perf_counter() - started_at) * 1000),
        )
