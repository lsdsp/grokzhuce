from __future__ import annotations

import os
from typing import Dict, Iterable, Optional

DEFAULT_PROXY_ENV_KEYS = (
    "GROK_PROXY_URL",
    "MOEMAIL_PROXY_URL",
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)


def resolve_proxy_url(preferred_keys: Optional[Iterable[str]] = None) -> str:
    """Return the first non-empty proxy URL from preferred then default env keys."""
    checked = []
    for key in preferred_keys or ():
        if key not in checked:
            checked.append(key)
    for key in DEFAULT_PROXY_ENV_KEYS:
        if key not in checked:
            checked.append(key)

    for key in checked:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def build_requests_proxies(preferred_keys: Optional[Iterable[str]] = None) -> Dict[str, str]:
    """Build requests/curl_cffi proxy mapping from environment."""
    proxy_url = resolve_proxy_url(preferred_keys=preferred_keys)
    if not proxy_url:
        return {}
    return {"http": proxy_url, "https": proxy_url}
