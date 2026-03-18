from db_results import cleanup_old_results, init_db, load_result, save_result


class SolverResultRepository:
    async def init(self):
        await init_db()

    async def save_pending(self, task_id: str, *, url: str, sitekey: str, action=None, cdata=None):
        await save_result(
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
        await save_result(task_id, "turnstile", {"value": token, "elapsed_time": elapsed_time})

    async def save_failure(self, task_id: str, elapsed_time: float):
        await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL", "elapsed_time": elapsed_time})

    async def load(self, task_id: str):
        return await load_result(task_id)

    async def cleanup(self, days_old: int = 7):
        return await cleanup_old_results(days_old=days_old)

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
