from __future__ import annotations

import os
from typing import Any, Callable, Dict, Iterable, Optional

import urllib3
from urllib3.exceptions import InsecureRequestWarning

from .proxy_utils import build_requests_proxies

_VERIFY_TRUE_VALUES = {"true", "1", "yes", "on"}
_VERIFY_FALSE_VALUES = {"false", "0", "no", "off"}


def build_proxy_mapping(
    *,
    explicit_proxy_url: str = "",
    preferred_proxy_keys: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    proxy_url = (explicit_proxy_url or "").strip()
    if proxy_url:
        return {"http": proxy_url, "https": proxy_url}
    return build_requests_proxies(preferred_keys=preferred_proxy_keys)


def should_verify_ssl(verify_ssl_env: Optional[str], proxy_url: str) -> bool:
    raw = (verify_ssl_env or "").strip().lower()
    if raw in _VERIFY_TRUE_VALUES:
        return True
    if raw in _VERIFY_FALSE_VALUES:
        return False
    return not bool((proxy_url or "").strip())


def build_plain_request_kwargs(
    *,
    preferred_proxy_keys: Optional[Iterable[str]] = None,
    explicit_proxy_url: str = "",
    verify_ssl_env_key: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    proxies = build_proxy_mapping(
        explicit_proxy_url=explicit_proxy_url,
        preferred_proxy_keys=preferred_proxy_keys,
    )
    proxy_url = proxies.get("https") or proxies.get("http") or ""
    verify = should_verify_ssl(
        os.getenv(verify_ssl_env_key) if verify_ssl_env_key else None,
        proxy_url,
    )
    if not verify:
        urllib3.disable_warnings(InsecureRequestWarning)

    kwargs: Dict[str, Any] = {"verify": verify}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if proxies:
        kwargs["proxies"] = proxies
    return kwargs


def build_impersonated_request_kwargs(
    *,
    preferred_proxy_keys: Optional[Iterable[str]] = None,
    explicit_proxy_url: str = "",
    impersonate: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"impersonate": impersonate or "chrome120"}
    if timeout is not None:
        kwargs["timeout"] = timeout

    proxies = build_proxy_mapping(
        explicit_proxy_url=explicit_proxy_url,
        preferred_proxy_keys=preferred_proxy_keys,
    )
    if proxies:
        kwargs["proxies"] = proxies
    return kwargs


def create_local_session(session_factory: Callable[[], Any]):
    session = session_factory()
    session.trust_env = False
    return session
