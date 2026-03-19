import re
import time
from contextlib import nullcontext

from grok_protocol_common import generate_random_name
from grok_runtime import ErrorType, StageResult


SIGNUP_RETRY_PER_CODE = 3


def extract_set_cookie_redirect_url(response_text: str) -> str:
    match = re.search(r'(https://[^"\s]+set-cookie\?q=[^"\s}]+)', response_text or "")
    return match.group(1) if match else ""


def attempt_signup(
    *,
    session,
    turnstile_service,
    runtime,
    site_url: str,
    email: str,
    password: str,
    code: str,
    impersonate: str,
    user_agent: str,
    post_lock=None,
) -> StageResult:
    for _ in range(SIGNUP_RETRY_PER_CODE):
        task_id = turnstile_service.create_task(site_url, runtime.site_key)
        token = turnstile_service.get_response(task_id)
        if not token or token == "CAPTCHA_FAIL":
            continue

        headers = {
            "user-agent": user_agent,
            "accept": "text/x-component",
            "content-type": "text/plain;charset=UTF-8",
            "origin": site_url,
            "referer": f"{site_url}/sign-up",
            "cookie": f"__cf_bm={session.cookies.get('__cf_bm', '')}",
            "next-router-state-tree": runtime.state_tree,
            "next-action": runtime.action_id,
        }
        payload = [
            {
                "emailValidationCode": code,
                "createUserAndSessionRequest": {
                    "email": email,
                    "givenName": generate_random_name(),
                    "familyName": generate_random_name(),
                    "clearTextPassword": password,
                    "tosAcceptedVersion": "$undefined",
                },
                "turnstileToken": token,
                "promptOnDuplicateEmail": True,
            }
        ]

        lock_ctx = post_lock if post_lock is not None else nullcontext()
        with lock_ctx:
            response = session.post(f"{site_url}/sign-up", json=payload, headers=headers, timeout=45)

        body = (response.text or "").lower()
        if "invalid-validation-code" in body or "email validation code is invalid" in body:
            return StageResult(False, "signup", ErrorType.SIGNUP, True, "验证码失效", data={"code_invalid": True})

        if response.status_code != 200:
            time.sleep(3)
            continue

        redirect_url = extract_set_cookie_redirect_url(response.text)
        if not redirect_url:
            break

        back = session.get(redirect_url, allow_redirects=True, timeout=30)
        _ = back.status_code
        sso = session.cookies.get("sso") or ""
        sso_rw = session.cookies.get("sso-rw") or ""
        if not sso:
            break

        return StageResult(
            True,
            "signup",
            data={
                "sso": sso,
                "sso_rw": sso_rw,
                "impersonate": impersonate,
                "user_agent": user_agent,
            },
        )

    return StageResult(False, "signup", ErrorType.SIGNUP, True, "注册重试耗尽")
