from __future__ import annotations

import datetime as dt
import os
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse

from curl_cffi import requests
from dotenv import load_dotenv
from .proxy_utils import build_requests_proxies

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_NSFW_SEMAPHORE = None
_NSFW_SEM_VALUE = None
_NSFW_SEM_LOCK = threading.Lock()


def _parse_positive_int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _get_nsfw_semaphore() -> threading.Semaphore:
    value = _parse_positive_int_env("NSFW_CONCURRENT", 3)
    global _NSFW_SEMAPHORE, _NSFW_SEM_VALUE
    with _NSFW_SEM_LOCK:
        if _NSFW_SEMAPHORE is None or _NSFW_SEM_VALUE != value:
            _NSFW_SEM_VALUE = value
            _NSFW_SEMAPHORE = threading.Semaphore(value)
    return _NSFW_SEMAPHORE


class NsfwSettingsService:
    """开启 NSFW 相关设置（线程安全，无全局状态）。"""

    def __init__(self, cf_clearance: str = "", proxy_url: str = ""):
        self.cf_clearance = (cf_clearance or "").strip()
        if proxy_url and proxy_url.strip():
            proxy = proxy_url.strip()
            self.proxies = {"http": proxy, "https": proxy}
        else:
            self.proxies = build_requests_proxies(preferred_keys=("GROK_PROXY_URL",))
        self._unhinged_checked = False
        self._unhinged_supported_key: Optional[str] = None
        self.request_timeout = _parse_positive_int_env("NSFW_TIMEOUT", 20)
        self.retry_attempts = _parse_positive_int_env("NSFW_RETRY_ATTEMPTS", 2)

    @staticmethod
    def _build_feature_control_payload(feature_name: str, enabled: bool = True) -> bytes:
        """
        构造 UpdateUserFeatureControls gRPC-Web payload:
        message {
          field1: message { field2: bool enabled }
          field2: message { field1: string feature_name }
        }
        """
        feature_bytes = feature_name.encode("utf-8")
        if len(feature_bytes) > 127:
            raise ValueError("feature_name is too long")
        flag = b"\x10\x01" if enabled else b"\x10\x00"
        payload = (
            b"\x0a\x02" + flag +
            b"\x12" + bytes([0x02 + len(feature_bytes)]) +
            b"\x0a" + bytes([len(feature_bytes)]) + feature_bytes
        )
        return b"\x00\x00\x00\x00" + bytes([len(payload)]) + payload

    @staticmethod
    def _build_headers(
        origin: str,
        referer: str,
        user_agent: str,
        content_type: str,
        include_grpc_headers: bool = True,
    ) -> Dict[str, str]:
        origin_host = urlparse(origin).hostname or ""
        referer_host = urlparse(referer).hostname or ""
        fetch_site = "same-origin" if origin_host and referer_host and origin_host == referer_host else "same-site"
        headers = {
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "baggage": (
                "sentry-environment=production,"
                "sentry-release=d6add6fb0460641fd482d767a335ef72b9b6abb8,"
                "sentry-public_key=b311e0f2690c81f25e2c4cf6d4f7ce1c"
            ),
            "content-type": content_type,
            "origin": origin,
            "referer": referer,
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "sec-fetch-site": fetch_site,
            "priority": "u=1, i",
            "x-statsig-id": str(uuid.uuid4()),
            "x-xai-request-id": str(uuid.uuid4()),
            "user-agent": user_agent,
            "cache-control": "no-cache",
            "pragma": "no-cache",
        }
        if include_grpc_headers:
            headers["x-grpc-web"] = "1"
            headers["x-user-agent"] = "connect-es/2.1.1"
        return headers

    def _post_with_retries(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        cookies: Optional[Dict[str, str]],
        impersonate: str,
        timeout: int,
        data: Optional[bytes] = None,
        json_data: Optional[Dict[str, Any]] = None,
        retry_on_status: Tuple[int, ...] = (429, 500, 502, 503, 504),
    ):
        attempts = max(1, self.retry_attempts)
        last_exc = None
        for attempt in range(1, attempts + 1):
            try:
                with _get_nsfw_semaphore():
                    kwargs = {
                        "headers": headers,
                        "data": data,
                        "json": json_data,
                        "impersonate": impersonate,
                        "timeout": timeout,
                        "proxies": self.proxies or None,
                    }
                    if cookies:
                        kwargs["cookies"] = cookies
                    response = requests.post(url, **kwargs)
                if response.status_code in retry_on_status and attempt < attempts:
                    time.sleep(min(0.5 * attempt, 2.0))
                    continue
                return response
            except Exception as e:
                last_exc = e
                if attempt < attempts:
                    time.sleep(min(0.5 * attempt, 2.0))
                    continue
                raise
        if last_exc:
            raise last_exc
        raise RuntimeError("post retry exhausted")

    @staticmethod
    def _build_birth_date() -> str:
        today = dt.date.today()
        birth_year = today.year - random.randint(20, 48)
        birth_month = random.randint(1, 12)
        birth_day = random.randint(1, 28)
        hour = random.randint(0, 23)
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        millisecond = random.randint(0, 999)
        return (
            f"{birth_year:04d}-{birth_month:02d}-{birth_day:02d}"
            f"T{hour:02d}:{minute:02d}:{second:02d}.{millisecond:03d}Z"
        )

    @staticmethod
    def _build_cookie_header(sso: str, sso_rw: Optional[str], cf_clearance: str) -> str:
        cookie = f"sso={sso}; sso-rw={sso_rw or sso}"
        if cf_clearance:
            cookie += f"; cf_clearance={cf_clearance}"
        return cookie

    def set_birth_date(
        self,
        sso: str,
        sso_rw: Optional[str] = None,
        impersonate: str = "chrome120",
        user_agent: Optional[str] = None,
        cf_clearance: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        对齐参考实现：在 grok.com 设置出生日期（NSFW 前置步骤）。
        """
        if not sso:
            return {"ok": False, "status_code": None, "error": "缺少 sso"}

        clearance = (cf_clearance if cf_clearance is not None else self.cf_clearance).strip()

        payload = {"birthDate": self._build_birth_date()}

        try:
            endpoints = [
                ("https://grok.com/rest/auth/set-birth-date", "https://grok.com", "https://grok.com/?_s=home"),
                ("https://accounts.x.ai/rest/auth/set-birth-date", "https://accounts.x.ai", "https://accounts.x.ai/"),
            ]
            last_result = None
            for url, origin, referer in endpoints:
                headers = self._build_headers(
                    origin=origin,
                    referer=referer,
                    user_agent=user_agent or DEFAULT_USER_AGENT,
                    content_type="application/json",
                    include_grpc_headers=False,
                )
                request_cookies = {"sso": sso, "sso-rw": (sso_rw or sso)}
                if clearance:
                    request_cookies["cf_clearance"] = clearance
                if "grok.com" in url:
                    headers["cookie"] = self._build_cookie_header(sso=sso, sso_rw=sso, cf_clearance=clearance)
                    request_cookies = None

                response = self._post_with_retries(
                    url=url,
                    headers=headers,
                    cookies=request_cookies,
                    json_data=payload,
                    impersonate=impersonate or "chrome120",
                    timeout=timeout or self.request_timeout,
                )
                ok = response.status_code in (200, 204)
                error = None
                if not ok:
                    error = f"HTTP {response.status_code}"
                last_result = {
                    "ok": ok,
                    "status_code": response.status_code,
                    "error": error,
                    "endpoint": url,
                }
                if ok:
                    return last_result
                if response.status_code in (403, 404):
                    continue
                return last_result

            return last_result or {
                "ok": False,
                "status_code": None,
                "error": "No endpoint available",
                "endpoint": None,
            }
        except Exception as e:
            return {
                "ok": False,
                "status_code": None,
                "error": str(e),
                "endpoint": None,
            }

    def enable_nsfw(
        self,
        sso: str,
        sso_rw: str,
        impersonate: str,
        user_agent: Optional[str] = None,
        cf_clearance: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        启用 always_show_nsfw_content。
        返回: {
            ok: bool,
            hex_reply: str,
            status_code: int | None,
            grpc_status: str | None,
            error: str | None
        }
        """
        if not sso:
            return {
                "ok": False,
                "hex_reply": "",
                "status_code": None,
                "grpc_status": None,
                "error": "缺少 sso",
            }
        if not sso_rw:
            return {
                "ok": False,
                "hex_reply": "",
                "status_code": None,
                "grpc_status": None,
                "error": "缺少 sso-rw",
            }

        cookies = {
            "sso": sso,
            "sso-rw": sso_rw,
        }
        clearance = (cf_clearance if cf_clearance is not None else self.cf_clearance).strip()
        if clearance:
            cookies["cf_clearance"] = clearance

        data = self._build_feature_control_payload("always_show_nsfw_content", enabled=True)

        try:
            # 参考实现优先走 grok.com；兼容旧路径回退 accounts.x.ai。
            endpoints = [
                ("https://grok.com/auth_mgmt.AuthManagement/UpdateUserFeatureControls", "https://grok.com", "https://grok.com/?_s=data"),
                ("https://accounts.x.ai/auth_mgmt.AuthManagement/UpdateUserFeatureControls", "https://accounts.x.ai", "https://accounts.x.ai/"),
            ]
            last_result = None
            for url, origin, referer in endpoints:
                headers = self._build_headers(
                    origin=origin,
                    referer=referer,
                    user_agent=user_agent or DEFAULT_USER_AGENT,
                    content_type="application/grpc-web+proto",
                )
                request_cookies = cookies
                if "grok.com" in url:
                    headers["cookie"] = self._build_cookie_header(
                        sso=sso,
                        sso_rw=sso,
                        cf_clearance=clearance,
                    )
                    request_cookies = None
                response = self._post_with_retries(
                    url=url,
                    headers=headers,
                    cookies=request_cookies,
                    data=data,
                    impersonate=impersonate or "chrome120",
                    timeout=timeout or self.request_timeout,
                )
                hex_reply = response.content.hex()
                grpc_status = response.headers.get("grpc-status")
                ok = response.status_code == 200 and (grpc_status in (None, "0"))
                error = None
                if response.status_code == 403:
                    error = "403 Forbidden"
                elif response.status_code != 200:
                    error = f"HTTP {response.status_code}"
                elif grpc_status not in (None, "0"):
                    error = f"gRPC {grpc_status}"

                last_result = {
                    "ok": ok,
                    "hex_reply": hex_reply,
                    "status_code": response.status_code,
                    "grpc_status": grpc_status,
                    "error": error,
                    "endpoint": url,
                }
                if ok:
                    return last_result
                # 403/404 常见于域策略差异，继续回退尝试。
                if response.status_code in (403, 404):
                    continue
                return last_result
            return last_result or {
                "ok": False,
                "hex_reply": "",
                "status_code": None,
                "grpc_status": None,
                "error": "No endpoint available",
            }
        except Exception as e:
            return {
                "ok": False,
                "hex_reply": "",
                "status_code": None,
                "grpc_status": None,
                "error": str(e),
            }

    def enable_unhinged(
        self,
        sso: str,
        sso_rw: Optional[str] = None,
        impersonate: str = "chrome120",
        user_agent: Optional[str] = None,
        cf_clearance: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        尝试开启 Unhinged 模式（二次验证）。
        若服务端不支持该 feature（常见 grpc=3/13），将优雅降级为 supported=False，避免反复告警。
        """
        if not sso:
            return {"ok": False, "supported": False, "status_code": None, "error": "缺少 sso"}

        cookies = {"sso": sso, "sso-rw": (sso_rw or sso)}
        clearance = (cf_clearance if cf_clearance is not None else self.cf_clearance).strip()
        if clearance:
            cookies["cf_clearance"] = clearance

        if self._unhinged_checked and self._unhinged_supported_key is None:
            return {
                "ok": True,
                "supported": False,
                "status_code": 200,
                "grpc_status": "unsupported",
                "error": None,
            }

        feature_candidates = []
        env_feature = (os.getenv("UNHINGED_FEATURE_KEY") or "").strip()
        if env_feature:
            feature_candidates.append(env_feature)
        feature_candidates.extend([
            "always_enable_unhinged_mode",
            "always_use_unhinged_mode",
            "always_unhinged_mode",
            "unhinged_mode",
            "always_unhinged",
        ])
        # 保序去重
        dedup_candidates = list(dict.fromkeys([item for item in feature_candidates if item]))
        if self._unhinged_supported_key:
            dedup_candidates = [self._unhinged_supported_key]

        try:
            last_status_code = None
            last_grpc_status = None
            last_error = None
            last_endpoint = None

            endpoints = [
                ("https://grok.com/auth_mgmt.AuthManagement/UpdateUserFeatureControls", "https://grok.com", "https://grok.com/?_s=data"),
                ("https://accounts.x.ai/auth_mgmt.AuthManagement/UpdateUserFeatureControls", "https://accounts.x.ai", "https://accounts.x.ai/"),
            ]

            for feature_key in dedup_candidates:
                data = self._build_feature_control_payload(feature_key, enabled=True)
                for url, origin, referer in endpoints:
                    headers = self._build_headers(
                        origin=origin,
                        referer=referer,
                        user_agent=user_agent or DEFAULT_USER_AGENT,
                        content_type="application/grpc-web+proto",
                    )
                    request_cookies = cookies
                    if "grok.com" in url:
                        headers["cookie"] = self._build_cookie_header(
                            sso=sso,
                            sso_rw=sso,
                            cf_clearance=clearance,
                        )
                        request_cookies = None
                    response = self._post_with_retries(
                        url=url,
                        headers=headers,
                        cookies=request_cookies,
                        data=data,
                        impersonate=impersonate,
                        timeout=timeout or self.request_timeout,
                    )
                    grpc_status = response.headers.get("grpc-status")
                    last_status_code = response.status_code
                    last_grpc_status = grpc_status
                    last_endpoint = url

                    if response.status_code == 200 and grpc_status in (None, "0"):
                        self._unhinged_checked = True
                        self._unhinged_supported_key = feature_key
                        return {
                            "ok": True,
                            "supported": True,
                            "status_code": response.status_code,
                            "grpc_status": grpc_status,
                            "error": None,
                            "feature_key": feature_key,
                            "endpoint": url,
                        }

                    if response.status_code == 200 and grpc_status in ("3", "13", "12"):
                        # Feature 不存在或服务端不支持，尝试下一个候选。
                        last_error = f"gRPC {grpc_status}"
                        break

                    # 403/404 尝试回退域，其余直接返回失败。
                    if response.status_code in (403, 404):
                        last_error = f"HTTP {response.status_code}"
                        continue

                    if response.status_code != 200:
                        last_error = f"HTTP {response.status_code}"
                    elif grpc_status not in (None, "0"):
                        last_error = f"gRPC {grpc_status}"

                    return {
                        "ok": False,
                        "supported": True,
                        "status_code": response.status_code,
                        "grpc_status": grpc_status,
                        "error": last_error,
                        "endpoint": url,
                    }

            # 所有候选都不被支持，优雅降级（不再告警）。
            self._unhinged_checked = True
            self._unhinged_supported_key = None
            return {
                "ok": True,
                "supported": False,
                "status_code": last_status_code or 200,
                "grpc_status": last_grpc_status or "unsupported",
                "error": None,
                "endpoint": last_endpoint,
            }
        except Exception as e:
            return {
                "ok": False,
                "supported": True,
                "status_code": None,
                "grpc_status": None,
                "error": str(e),
            }
