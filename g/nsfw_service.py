from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Dict, Any

from curl_cffi import requests
from dotenv import load_dotenv
from .proxy_utils import build_requests_proxies

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


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

    def enable_nsfw(
        self,
        sso: str,
        sso_rw: str,
        impersonate: str,
        user_agent: Optional[str] = None,
        cf_clearance: Optional[str] = None,
        timeout: int = 15,
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

        # 与注册/验码/TOS 保持同源，避免跨域风控导致 403。
        url = "https://accounts.x.ai/auth_mgmt.AuthManagement/UpdateUserFeatureControls"

        cookies = {
            "sso": sso,
            "sso-rw": sso_rw,
        }
        clearance = (cf_clearance if cf_clearance is not None else self.cf_clearance).strip()
        if clearance:
            cookies["cf_clearance"] = clearance

        headers = {
            "accept": "*/*",
            "content-type": "application/grpc-web+proto",
            "origin": "https://accounts.x.ai",
            "referer": "https://accounts.x.ai/",
            "x-grpc-web": "1",
            "x-user-agent": "connect-es/2.1.1",
            "user-agent": user_agent or DEFAULT_USER_AGENT,
        }

        data = self._build_feature_control_payload("always_show_nsfw_content", enabled=True)

        try:
            response = requests.post(
                url,
                headers=headers,
                cookies=cookies,
                data=data,
                impersonate=impersonate or "chrome120",
                timeout=timeout,
                proxies=self.proxies or None,
            )
            hex_reply = response.content.hex()
            grpc_status = response.headers.get("grpc-status")

            error = None
            ok = response.status_code == 200 and (grpc_status in (None, "0"))
            if response.status_code == 403:
                error = "403 Forbidden"
            elif response.status_code != 200:
                error = f"HTTP {response.status_code}"
            elif grpc_status not in (None, "0"):
                error = f"gRPC {grpc_status}"

            return {
                "ok": ok,
                "hex_reply": hex_reply,
                "status_code": response.status_code,
                "grpc_status": grpc_status,
                "error": error,
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
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        尝试开启 Unhinged 模式（二次验证）。
        若服务端不支持该 feature（常见 grpc=3/13），将优雅降级为 supported=False，避免反复告警。
        """
        if not sso:
            return {"ok": False, "supported": False, "status_code": None, "error": "缺少 sso"}

        url = "https://accounts.x.ai/auth_mgmt.AuthManagement/UpdateUserFeatureControls"

        headers = {
            "accept": "*/*",
            "content-type": "application/grpc-web+proto",
            "origin": "https://accounts.x.ai",
            "referer": "https://accounts.x.ai/",
            "user-agent": user_agent or DEFAULT_USER_AGENT,
            "x-grpc-web": "1",
            "x-user-agent": "connect-es/2.1.1",
        }
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

            for feature_key in dedup_candidates:
                data = self._build_feature_control_payload(feature_key, enabled=True)
                response = requests.post(
                    url,
                    headers=headers,
                    cookies=cookies,
                    data=data,
                    impersonate=impersonate,
                    timeout=timeout,
                    proxies=self.proxies or None,
                )
                grpc_status = response.headers.get("grpc-status")
                last_status_code = response.status_code
                last_grpc_status = grpc_status

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
                    }

                if response.status_code == 200 and grpc_status in ("3", "13", "12"):
                    # Feature 不存在或服务端不支持，尝试下一个候选。
                    last_error = f"gRPC {grpc_status}"
                    continue

                # 其他异常响应保留为真实失败。
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
            }
        except Exception as e:
            return {
                "ok": False,
                "supported": True,
                "status_code": None,
                "grpc_status": None,
                "error": str(e),
            }
