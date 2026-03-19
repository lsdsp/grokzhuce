from db_results import default_result_store
from urllib.parse import urlsplit, urlunsplit


def redact_proxy_value(proxy):
    if not isinstance(proxy, str) or not proxy:
        return proxy
    if "@" in proxy:
        if "://" not in proxy:
            credentials, host = proxy.rsplit("@", 1)
            redacted = "***:***" if ":" in credentials else "***"
            return f"{redacted}@{host}"
        parts = urlsplit(proxy)
        if "@" not in parts.netloc:
            return proxy
        credentials, host = parts.netloc.rsplit("@", 1)
        redacted = "***:***" if ":" in credentials else "***"
        return urlunsplit((parts.scheme, f"{redacted}@{host}", parts.path, parts.query, parts.fragment))
    parts = proxy.split(":")
    if len(parts) == 5:
        proxy_scheme, proxy_ip, proxy_port, _proxy_user, _proxy_pass = parts
        return f"{proxy_scheme}:{proxy_ip}:{proxy_port}:***:***"
    return proxy


class SolverResultRepository:
    def __init__(self, store=None):
        self.store = store or default_result_store

    async def init(self):
        await self.store.init()

    async def save_pending(self, task_id: str, *, url: str, sitekey: str, action=None, cdata=None):
        await self.store.save(
            task_id,
            "turnstile",
            {
                "status": "CAPTCHA_NOT_READY",
                "url": url,
                "sitekey": sitekey,
                "action": action,
                "cdata": cdata,
            },
        )

    async def save_token(self, task_id: str, token: str, elapsed_time: float):
        await self.store.save(task_id, "turnstile", {"value": token, "elapsed_time": elapsed_time})

    async def save_failure(self, task_id: str, elapsed_time: float, **diagnostics):
        payload = {"value": "CAPTCHA_FAIL", "elapsed_time": elapsed_time}
        payload.update({key: value for key, value in diagnostics.items() if value not in (None, "")})
        await self.store.save(task_id, "turnstile", payload)

    async def load(self, task_id: str):
        return await self.store.load(task_id)

    async def cleanup(self, days_old: int = 7):
        return await self.store.cleanup(days_old=days_old)

    @staticmethod
    def _redact_proxy_value(proxy):
        return redact_proxy_value(proxy)

    def build_result_payload(self, result):
        if not result:
            return {
                "errorId": 1,
                "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
                "errorDescription": "Task not found",
            }

        if isinstance(result, dict):
            value = result.get("value")
            if value == "CAPTCHA_FAIL":
                payload = {
                    "errorId": 1,
                    "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
                    "errorDescription": "Workers could not solve the Captcha",
                }
                diagnostics = {}
                for key in ("failure_reason", "failed_stage", "browser_index", "proxy", "elapsed_time", "browser_name", "browser_version"):
                    if key in result and result.get(key) not in (None, ""):
                        value = result.get(key)
                        if key == "proxy":
                            value = self._redact_proxy_value(value)
                        diagnostics[key] = value
                if diagnostics:
                    payload["diagnostics"] = diagnostics
                return payload
            if value:
                return {
                    "errorId": 0,
                    "status": "ready",
                    "solution": {"token": value},
                }
            if result.get("status") == "CAPTCHA_NOT_READY":
                return {"status": "processing"}

        if result == "CAPTCHA_NOT_READY":
            return {"status": "processing"}

        return {
            "errorId": 1,
            "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
            "errorDescription": "Workers could not solve the Captcha",
        }
