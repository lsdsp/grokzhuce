from db_results import default_result_store


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

    async def save_failure(self, task_id: str, elapsed_time: float):
        await self.store.save(task_id, "turnstile", {"value": "CAPTCHA_FAIL", "elapsed_time": elapsed_time})

    async def load(self, task_id: str):
        return await self.store.load(task_id)

    async def cleanup(self, days_old: int = 7):
        return await self.store.cleanup(days_old=days_old)

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
                return {
                    "errorId": 1,
                    "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
                    "errorDescription": "Workers could not solve the Captcha",
                }
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
