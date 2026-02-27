"""邮箱服务类 - 基于 moemail OpenAPI。"""
import os
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3
from dotenv import load_dotenv
from urllib3.exceptions import InsecureRequestWarning
from .proxy_utils import build_requests_proxies, resolve_proxy_url


class EmailService:
    """临时邮箱服务封装（兼容原项目接口）。"""

    DEFAULT_EMAIL_EXPIRY_MS = 24 * 60 * 60 * 1000

    CODE_CONTEXT_PREFIX = r"(?:验证码|verification[\s-]*code|code)"
    CODE_CONTEXT_PATTERN = re.compile(
        rf"{CODE_CONTEXT_PREFIX}(?:\s*is)?[^0-9]{{0,24}}(\d{{4,8}})",
        re.IGNORECASE,
    )
    CODE_CONTEXT_SPLIT_PATTERN = re.compile(
        rf"{CODE_CONTEXT_PREFIX}(?:\s*is)?[^0-9]{{0,24}}([0-9][0-9\-\s]{{2,24}}[0-9])",
        re.IGNORECASE,
    )
    CODE_FALLBACK_PATTERN = re.compile(r"\b(\d{4,8})\b")
    CODE_SUBJECT_ALNUM_PATTERN = re.compile(r"\b([A-Z0-9]{3,4}[\-\s]?[A-Z0-9]{3,4})\b", re.IGNORECASE)

    def __init__(self):
        load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")
        self.moemail_api_url = os.getenv("MOEMAIL_API_URL", "https://api.moemail.app")
        self.moemail_api_key = os.getenv("MOEMAIL_API_KEY")
        if not self.moemail_api_key:
            raise ValueError("Missing: MOEMAIL_API_KEY")

        self.base_url = self.moemail_api_url.rstrip("/")
        self.x_api_key_headers = {
            "X-API-Key": self.moemail_api_key,
            "Content-Type": "application/json",
        }
        # 兼容少量自建镜像服务；官方 OpenAPI 使用 X-API-Key。
        self.bearer_headers = {
            "Authorization": f"Bearer {self.moemail_api_key}",
            "Content-Type": "application/json",
        }
        self.header_candidates = [self.x_api_key_headers, self.bearer_headers]

        proxy_url = resolve_proxy_url(preferred_keys=("MOEMAIL_PROXY_URL", "GROK_PROXY_URL"))
        verify_ssl_env = os.getenv("MOEMAIL_VERIFY_SSL")
        if verify_ssl_env is None or not verify_ssl_env.strip():
            verify_ssl = not bool(proxy_url)
        else:
            verify_ssl = verify_ssl_env.strip().lower() not in {"0", "false", "no", "off"}

        self.request_kwargs = {"verify": verify_ssl}
        if not verify_ssl:
            # In proxy MITM mode, verify=False is explicit; suppress repetitive warning noise.
            urllib3.disable_warnings(InsecureRequestWarning)
        proxy_mapping = build_requests_proxies(
            preferred_keys=("MOEMAIL_PROXY_URL", "GROK_PROXY_URL")
        )
        if proxy_mapping:
            self.request_kwargs["proxies"] = proxy_mapping

        self._email_id_cache: Dict[str, str] = {}
        self._email_created_at_ms: Dict[str, int] = {}

    @staticmethod
    def _extract_email(payload: Any) -> Optional[str]:
        if not payload:
            return None
        if isinstance(payload, list):
            for item in payload:
                email = EmailService._extract_email(item)
                if email:
                    return email
            return None
        if isinstance(payload, dict):
            for key in ("email", "address", "mailbox"):
                value = payload.get(key)
                if isinstance(value, str) and "@" in value:
                    return value
            for key in ("data", "result", "message"):
                nested = payload.get(key)
                if isinstance(nested, (dict, list)):
                    email = EmailService._extract_email(nested)
                    if email:
                        return email
        return None

    @staticmethod
    def _extract_email_id(payload: Any) -> Optional[str]:
        if isinstance(payload, dict):
            value = payload.get("id")
            if isinstance(value, str) and value:
                return value
            for key in ("data", "result", "message"):
                nested = payload.get(key)
                extracted = EmailService._extract_email_id(nested)
                if extracted:
                    return extracted
        if isinstance(payload, list):
            for item in payload:
                extracted = EmailService._extract_email_id(item)
                if extracted:
                    return extracted
        return None

    @staticmethod
    def _extract_email_items(payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("emails", "messages", "data", "result", "items"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
            if isinstance(nested, dict):
                return [nested]
        return [payload]

    @staticmethod
    def _extract_verification_code(email_item: Any) -> Optional[str]:
        if not isinstance(email_item, dict):
            return None

        for key in ("verification_code", "verificationCode", "code"):
            value = email_item.get(key)
            if isinstance(value, str) and value.strip():
                return value

        for key in ("text", "html", "subject", "content", "body"):
            value = email_item.get(key)
            if not isinstance(value, str):
                continue
            if key == "subject":
                match = EmailService.CODE_SUBJECT_ALNUM_PATTERN.search(value)
                if match:
                    normalized = EmailService._sanitize_alnum_code(match.group(1))
                    if 6 <= len(normalized) <= 8:
                        return normalized
            match = EmailService.CODE_CONTEXT_PATTERN.search(value)
            if match:
                return match.group(1)
            match = EmailService.CODE_CONTEXT_SPLIT_PATTERN.search(value)
            if match:
                normalized = EmailService._sanitize_verification_code(match.group(1))
                if 4 <= len(normalized) <= 8:
                    return normalized

            # 兜底仅用于主题/纯文本，避免在 HTML 大文本里误命中无关数字。
            if key in ("subject", "text"):
                fallback_codes = EmailService.CODE_FALLBACK_PATTERN.findall(value)
                fallback_codes = [c for c in fallback_codes if c]
                if len(fallback_codes) == 1:
                    return fallback_codes[0]

        return None

    @staticmethod
    def _sanitize_verification_code(code: str) -> str:
        return re.sub(r"\D+", "", code or "")

    @staticmethod
    def _sanitize_alnum_code(code: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "", code or "").upper()

    @staticmethod
    def _normalize_verification_code(code: str) -> str:
        if not code:
            return ""
        if re.search(r"[A-Za-z]", code):
            normalized = EmailService._sanitize_alnum_code(code)
            return normalized if 6 <= len(normalized) <= 8 else ""
        normalized = EmailService._sanitize_verification_code(code)
        return normalized if 4 <= len(normalized) <= 8 else ""

    @staticmethod
    def _to_timestamp_ms(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            n = int(value)
            if n > 10_000_000_000:  # 毫秒
                return n
            if n > 0:
                return n * 1000  # 秒
            return None
        if isinstance(value, str):
            v = value.strip()
            if not v:
                return None
            if v.isdigit():
                return EmailService._to_timestamp_ms(int(v))
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp() * 1000)
            except ValueError:
                return None
        return None

    def _request(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: int = 15,
    ) -> Optional[requests.Response]:
        try:
            return requests.request(
                method=method,
                url=f"{self.base_url}{path}",
                headers=headers,
                params=params,
                json=json_data,
                timeout=timeout,
                **self.request_kwargs,
            )
        except Exception:
            return None

    def _get_default_domain(self) -> Optional[str]:
        for headers in self.header_candidates:
            res = self._request("GET", "/api/config", headers=headers, timeout=10)
            if not res or res.status_code != 200:
                continue
            try:
                payload = res.json()
            except Exception:
                continue

            if not isinstance(payload, dict):
                continue

            domains_raw = payload.get("emailDomains") or payload.get("domains")
            if isinstance(domains_raw, str):
                domain = domains_raw.split(",")[0].strip()
                if domain:
                    return domain
            if isinstance(domains_raw, list):
                for item in domains_raw:
                    if isinstance(item, str) and item.strip():
                        return item.strip()
        return None

    def _list_emails(
        self, params: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        for headers in self.header_candidates:
            res = self._request("GET", "/api/emails", headers=headers, params=params, timeout=12)
            if not res or res.status_code != 200:
                continue
            try:
                payload = res.json()
            except Exception:
                continue
            items = self._extract_email_items(payload)
            next_cursor = payload.get("nextCursor") if isinstance(payload, dict) else None
            return items, next_cursor if isinstance(next_cursor, str) else None
        return [], None

    def _list_email_messages(
        self, email_id: str, cursor: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        params = {"cursor": cursor} if cursor else None
        path = f"/api/emails/{email_id}"
        for headers in self.header_candidates:
            res = self._request("GET", path, headers=headers, params=params, timeout=12)
            if not res or res.status_code != 200:
                continue
            try:
                payload = res.json()
            except Exception:
                continue
            items = self._extract_email_items(payload)
            next_cursor = payload.get("nextCursor") if isinstance(payload, dict) else None
            return items, next_cursor if isinstance(next_cursor, str) else None
        return [], None

    def _get_message_detail(self, email_id: str, message_id: str) -> Optional[Dict[str, Any]]:
        path = f"/api/emails/{email_id}/{message_id}"
        for headers in self.header_candidates:
            res = self._request("GET", path, headers=headers, timeout=12)
            if not res or res.status_code != 200:
                continue
            try:
                payload = res.json() if res.text else {}
            except Exception:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("message"), dict):
                return payload["message"]
            if isinstance(payload, dict):
                return payload
        return None

    def _resolve_email_id(self, address: str) -> Optional[str]:
        if not address:
            return None

        cached = self._email_id_cache.get(address)
        if cached:
            return cached

        query_candidates = ({"email": address}, {"mailbox": address}, {})
        for base_params in query_candidates:
            cursor = None
            seen_cursors = set()
            for _ in range(12):
                params = dict(base_params)
                if cursor:
                    params["cursor"] = cursor
                if not params:
                    params = None

                emails, next_cursor = self._list_emails(params=params)
                if not emails and not next_cursor:
                    break

                for item in emails:
                    email = item.get("address") or item.get("email")
                    email_id = item.get("id")
                    if isinstance(email, str) and isinstance(email_id, str):
                        self._email_id_cache[email] = email_id
                        if email == address:
                            return email_id

                if not next_cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor

        return None

    def _message_matches_target(self, message: Dict[str, Any], email: str) -> bool:
        lower_email = email.lower()
        recipient_keys = ("to_address", "toAddress", "to", "recipient")
        recipient_values = [message.get(k) for k in recipient_keys]

        for value in recipient_values:
            if isinstance(value, str) and lower_email in value.lower():
                return True
            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, str) and lower_email in entry.lower():
                        return True

        for key in ("html", "content", "text"):
            content = message.get(key)
            if isinstance(content, str) and lower_email in content.lower():
                return True

        # 有些列表接口不返回收件人，不能因为缺字段就过滤掉。
        if all(v in (None, "", []) for v in recipient_values):
            return True
        return False

    def create_email(self) -> Tuple[Optional[str], Optional[str]]:
        """创建临时邮箱（保持与历史接口兼容，返回 (jwt, email)）。"""
        domain = self._get_default_domain()
        payload_candidates = []
        if domain:
            payload_candidates.append({"name": "", "domain": domain, "expiryTime": self.DEFAULT_EMAIL_EXPIRY_MS})
            payload_candidates.append({"domain": domain, "expiryTime": self.DEFAULT_EMAIL_EXPIRY_MS})
        payload_candidates.extend([{"expiryTime": self.DEFAULT_EMAIL_EXPIRY_MS}, {}])

        for payload_data in payload_candidates:
            for headers in self.header_candidates:
                res = self._request(
                    "POST",
                    "/api/emails/generate",
                    headers=headers,
                    json_data=payload_data,
                    timeout=12,
                )
                if not res or res.status_code != 200:
                    continue

                try:
                    payload = res.json()
                except Exception:
                    continue

                email = self._extract_email(payload)
                if not email:
                    continue

                email_id = self._extract_email_id(payload)
                if email_id:
                    self._email_id_cache[email] = email_id

                created_at = None
                if isinstance(payload, dict):
                    created_at = payload.get("createdAt") or payload.get("created_at")
                created_at_ms = self._to_timestamp_ms(created_at)
                if created_at_ms:
                    self._email_created_at_ms[email] = created_at_ms

                return email, email

        print("[-] 创建邮箱失败: moemail OpenAPI 返回异常")
        return None, None

    def fetch_verification_code(
        self, email: str, max_attempts: int = 30, exclude_codes: Optional[set] = None
    ) -> Optional[str]:
        """轮询获取验证码（官方 OpenAPI: /api/emails/{emailId}）。"""
        email_id = self._resolve_email_id(email)
        if not email_id:
            return None

        min_created_at_ms = self._email_created_at_ms.get(email)
        seen_message_ids = set()

        for _ in range(max_attempts):
            cursor = None
            seen_cursors = set()

            for _page in range(6):
                messages, next_cursor = self._list_email_messages(email_id=email_id, cursor=cursor)
                if not messages and not next_cursor:
                    break

                def _msg_time(item: Dict[str, Any]) -> int:
                    return (
                        self._to_timestamp_ms(item.get("received_at"))
                        or self._to_timestamp_ms(item.get("sent_at"))
                        or self._to_timestamp_ms(item.get("createdAt"))
                        or 0
                    )

                messages = sorted(messages, key=_msg_time, reverse=True)

                for message in messages:
                    if not isinstance(message, dict):
                        continue

                    msg_id = message.get("id")
                    if isinstance(msg_id, str) and msg_id in seen_message_ids:
                        continue

                    msg_time = _msg_time(message)
                    if min_created_at_ms and msg_time and msg_time + 1000 < min_created_at_ms:
                        continue

                    if not self._message_matches_target(message, email):
                        continue

                    candidates = [message]
                    if isinstance(msg_id, str) and msg_id:
                        detail = self._get_message_detail(email_id=email_id, message_id=msg_id)
                        if isinstance(detail, dict):
                            candidates.insert(0, detail)

                    for candidate in candidates:
                        code = self._extract_verification_code(candidate)
                        if code:
                            normalized = self._normalize_verification_code(code)
                            if normalized:
                                if exclude_codes and normalized in exclude_codes:
                                    continue
                                return normalized

                    if isinstance(msg_id, str):
                        seen_message_ids.add(msg_id)

                if not next_cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor

            time.sleep(1)

        return None

    def delete_email(self, address: str) -> bool:
        """删除邮箱（官方 OpenAPI: DELETE /api/emails/{emailId}）。"""
        email_id = self._resolve_email_id(address)
        if not email_id:
            return False

        for headers in self.header_candidates:
            res = self._request(
                "DELETE", f"/api/emails/{email_id}", headers=headers, timeout=12
            )
            if not res or res.status_code != 200:
                continue

            if not res.text.strip():
                return True
            try:
                payload = res.json()
            except Exception:
                return True

            if isinstance(payload, dict):
                if payload.get("success") is False:
                    continue
                return True
            return True

        return False
