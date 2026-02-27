"""
Turnstile验证服务类
"""
import os
import time
from pathlib import Path
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")


class TurnstileService:
    """Turnstile验证服务类"""
    YESCAPTCHA_TIMEOUT = 30

    def __init__(self, solver_url="http://127.0.0.1:5072"):
        """
        初始化Turnstile服务
        """
        self.yescaptcha_key = os.getenv('YESCAPTCHA_KEY', '').strip()
        self.solver_url = solver_url
        self.yescaptcha_api = "https://api.yescaptcha.com"
        # 本地 solver 访问不应被系统代理接管，否则 127.0.0.1 请求会被错误转发。
        self.local_session = requests.Session()
        self.local_session.trust_env = False

    def create_task(self, siteurl, sitekey):
        """
        创建Turnstile验证任务
        """
        if self.yescaptcha_key:
            # 使用 YesCaptcha API
            url = f"{self.yescaptcha_api}/createTask"
            payload = {
                "clientKey": self.yescaptcha_key,
                "task": {
                    "type": "TurnstileTaskProxyless",
                    "websiteURL": siteurl,
                    "websiteKey": sitekey
                }
            }
            response = requests.post(url, json=payload, timeout=self.YESCAPTCHA_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            if data.get('errorId') != 0:
                raise Exception(f"YesCaptcha创建任务失败: {data.get('errorDescription')}")
            return data['taskId']
        else:
            # 使用本地 Turnstile Solver
            query = urlencode({"url": siteurl, "sitekey": sitekey})
            url = f"{self.solver_url}/turnstile?{query}"
            response = self.local_session.get(url, timeout=15)
            response.raise_for_status()
            return response.json()['taskId']

    def get_response(self, task_id, max_retries=35, initial_delay=5, retry_delay=2):
        """
        获取Turnstile验证响应
        """
        time.sleep(initial_delay)

        for _ in range(max_retries):
            try:
                if self.yescaptcha_key:
                    # 使用 YesCaptcha API
                    url = f"{self.yescaptcha_api}/getTaskResult"
                    payload = {
                        "clientKey": self.yescaptcha_key,
                        "taskId": task_id
                    }
                    response = requests.post(url, json=payload, timeout=self.YESCAPTCHA_TIMEOUT)
                    response.raise_for_status()
                    data = response.json()

                    if data.get('errorId') != 0:
                        print(f"YesCaptcha获取结果失败: {data.get('errorDescription')}")
                        return None

                    if data.get('status') == 'ready':
                        token = data.get('solution', {}).get('token')
                        if token:
                            return token
                        else:
                            print("YesCaptcha返回结果中没有token")
                            return None
                    elif data.get('status') == 'processing':
                        time.sleep(retry_delay)
                    else:
                        print(f"YesCaptcha未知状态: {data.get('status')}")
                        time.sleep(retry_delay)
                else:
                    # 使用本地 Turnstile Solver
                    url = f"{self.solver_url}/result?id={task_id}"
                    response = self.local_session.get(url, timeout=15)
                    response.raise_for_status()
                    data = response.json()
                    status = data.get('status')
                    if status == 'ready':
                        captcha = data.get('solution', {}).get('token')
                        if captcha and captcha != "CAPTCHA_FAIL":
                            return captcha
                        return None

                    if status == 'processing':
                        time.sleep(retry_delay)
                        continue

                    # solver 明确返回不可解时，无需继续等待。
                    if data.get('errorId') == 1 and data.get('errorCode') == 'ERROR_CAPTCHA_UNSOLVABLE':
                        return None

                    # 兼容旧响应结构（无 status，仅返回 solution）。
                    captcha = data.get('solution', {}).get('token')
                    if captcha:
                        return captcha if captcha != "CAPTCHA_FAIL" else None

                    if data.get('errorId') == 1:
                        print(f"本地solver返回错误: {data.get('errorCode')} - {data.get('errorDescription')}")
                        return None

                    # 其他未知响应继续轮询，避免短暂中间态造成误判。
                    if status and status != 'processing':
                        print(f"本地solver未知状态: {status}")
                        time.sleep(retry_delay)
                    else:
                        time.sleep(retry_delay)
            except Exception as e:
                print(f"获取Turnstile响应异常: {e}")
                time.sleep(retry_delay)

        return None
