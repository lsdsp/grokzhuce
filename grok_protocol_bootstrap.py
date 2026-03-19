import re
import time
from typing import Sequence
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests

from grok_config import DEFAULT_IMPERSONATE, DEFAULT_SITE_URL
from grok_runtime import ErrorType, RuntimeContext, StageResult


SITE_KEY_PATTERNS = (
    r'sitekey":"(0x4[a-zA-Z0-9_-]+)"',
    r'"siteKey"\s*:\s*"(0x4[a-zA-Z0-9_-]+)"',
    r'data-sitekey=["\'](0x4[a-zA-Z0-9_-]+)["\']',
)
STATE_TREE_PATTERNS = (
    r'next-router-state-tree":"([^"]+)"',
    r'"next-router-state-tree"\s*:\s*"([^"]+)"',
    r'<meta[^>]+name=["\']next-router-state-tree["\'][^>]+content=["\']([^"\']+)["\']',
)
ACTION_ID_PATTERNS = (
    r'data-next-action=["\'](7f[a-fA-F0-9]{40})["\']',
    r'"next-action"\s*:\s*"(7f[a-fA-F0-9]{40})"',
    r"(7f[a-fA-F0-9]{40})",
)


def _find_first_match(text: str, patterns) -> str:
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            return match.group(1)
    return ""


def _compact_hint(text: str, limit: int = 120) -> str:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "..."


def extract_signup_bootstrap(*, html: str, js_bodies: Sequence[str], runtime: RuntimeContext) -> StageResult:
    normalized_html = html.replace('\\"', '"')

    site_key = _find_first_match(normalized_html, SITE_KEY_PATTERNS)
    if site_key:
        runtime.site_key = site_key

    state_tree = _find_first_match(normalized_html, STATE_TREE_PATTERNS)
    if state_tree:
        runtime.state_tree = state_tree

    for source_text in (normalized_html, *js_bodies):
        action_id = _find_first_match(source_text, ACTION_ID_PATTERNS)
        if action_id:
            runtime.action_id = action_id
            break

    if not runtime.action_id:
        html_hint = _compact_hint(normalized_html)
        js_hint = _compact_hint(" | ".join(js_bodies[:2]))
        return StageResult(
            False,
            "scan_bootstrap",
            ErrorType.PARSE,
            False,
            f"未找到 Action ID | html_hint={html_hint} | js_hint={js_hint}",
        )
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
