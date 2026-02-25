"""邮箱服务类 - 适配 moemail API"""
import os
import time
import requests
import re
from dotenv import load_dotenv


class EmailService:
    def __init__(self):
        load_dotenv()
        self.moemail_api_url = os.getenv("MOEMAIL_API_URL", "https://api.moemail.app")
        self.moemail_api_key = os.getenv("MOEMAIL_API_KEY")
        if not self.moemail_api_key:
            raise ValueError("Missing: MOEMAIL_API_KEY")
        self.base_url = self.moemail_api_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.moemail_api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _extract_email(payload):
        if not payload:
            return None
        if isinstance(payload, dict):
            for key in ("email", "address", "mailbox"):
                value = payload.get(key)
                if isinstance(value, str) and "@" in value:
                    return value
            for key in ("data", "result"):
                nested = payload.get(key)
                if isinstance(nested, dict):
                    email = EmailService._extract_email(nested)
                    if email:
                        return email
        return None

    @staticmethod
    def _extract_verification_code(email_item):
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
            code = re.search(r"\b(\d{4,8})\b", value)
            if code:
                return code.group(1)

        return None

    def create_email(self):
        """创建临时邮箱"""
        endpoints = [
            ("POST", "/api/emails/generate", {}),
            ("POST", "/api/email/new", {}),
            ("GET", "/api/generate", None),
        ]

        for method, path, json_data in endpoints:
            try:
                if method == "POST":
                    res = requests.post(
                        f"{self.base_url}{path}",
                        headers=self.headers,
                        json=json_data,
                        timeout=10,
                    )
                else:
                    res = requests.get(
                        f"{self.base_url}{path}",
                        headers=self.headers,
                        timeout=10,
                    )

                if res.status_code == 200:
                    email = self._extract_email(res.json())
                    if email:
                        return email, email  # 兼容原接口 (jwt, email)
            except Exception:
                continue

        print("[-] 创建邮箱失败: moemail API 不可用或返回格式不匹配")
        return None, None

    def fetch_verification_code(self, email, max_attempts=30):
        """轮询获取验证码"""
        endpoints = [
            ("GET", "/api/emails", {"mailbox": email}),
            ("GET", "/api/emails/messages", {"email": email}),
            ("GET", "/api/email/messages", {"address": email}),
        ]

        for _ in range(max_attempts):
            for method, path, params in endpoints:
                try:
                    if method != "GET":
                        continue

                    res = requests.get(
                        f"{self.base_url}{path}",
                        params=params,
                        headers=self.headers,
                        timeout=10,
                    )

                    if res.status_code != 200:
                        continue

                    payload = res.json()
                    emails = payload if isinstance(payload, list) else payload.get("data", [])
                    if not emails:
                        continue

                    code = self._extract_verification_code(emails[0])
                    if code:
                        return code.replace("-", "")
                except Exception:
                    continue

            time.sleep(1)

        return None

    def delete_email(self, address):
        """删除邮箱"""
        endpoints = [
            ("DELETE", "/api/emails", {"email": address}),
            ("DELETE", "/api/email", {"address": address}),
            ("DELETE", "/api/mailboxes", {"address": address}),
        ]

        for method, path, params in endpoints:
            try:
                if method != "DELETE":
                    continue

                res = requests.delete(
                    f"{self.base_url}{path}",
                    params=params,
                    headers=self.headers,
                    timeout=10,
                )
                if res.status_code == 200:
                    data = res.json() if res.text else {}
                    if isinstance(data, dict):
                        if data.get("success") is False:
                            continue
                    return True
            except Exception:
                continue

        return False
