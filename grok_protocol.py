import random
import re
import string
import struct
import time
from typing import Callable, Iterable, Optional, Sequence
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests

from grok_config import DEFAULT_IMPERSONATE, DEFAULT_SITE_URL
from grok_runtime import ErrorType, RuntimeContext, StageResult


CHROME_PROFILES = [
    {"impersonate": "chrome110", "version": "110.0.0.0", "brand": "chrome"},
    {"impersonate": "chrome119", "version": "119.0.0.0", "brand": "chrome"},
    {"impersonate": "chrome120", "version": "120.0.0.0", "brand": "chrome"},
    {"impersonate": "edge99", "version": "99.0.1150.36", "brand": "edge"},
    {"impersonate": "edge101", "version": "101.0.1210.47", "brand": "edge"},
]

EMAIL_CODE_REQUEST_ROUNDS = 3
EMAIL_CODE_POLL_ATTEMPTS_PER_ROUND = 180
MAX_EMAIL_CODE_CYCLES_PER_EMAIL = 3
SIGNUP_RETRY_PER_CODE = 3


def get_random_chrome_profile():
    profile = random.choice(CHROME_PROFILES)
    if profile["brand"] == "edge":
        chrome_major = profile["version"].split(".")[0]
        chrome_version = f"{chrome_major}.0.0.0"
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome_version} Safari/537.36 Edg/{profile['version']}"
        )
    else:
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{profile['version']} Safari/537.36"
        )
    return profile["impersonate"], ua


def compact_text(value, max_len=220):
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if len(text) <= max_len else text[:max_len] + "..."


def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        return f"{local[:1]}*@{domain}"
    return f"{local[:2]}***{local[-1]}@{domain}"


def generate_random_name() -> str:
    length = random.randint(4, 6)
    return random.choice(string.ascii_uppercase) + "".join(random.choice(string.ascii_lowercase) for _ in range(length - 1))


def generate_random_string(length: int = 15) -> str:
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))


def encode_grpc_message(field_id, string_value):
    key = (field_id << 3) | 2
    value_bytes = string_value.encode("utf-8")
    payload = struct.pack("B", key) + struct.pack("B", len(value_bytes)) + value_bytes
    return b"\x00" + struct.pack(">I", len(payload)) + payload


def encode_grpc_message_verify(email, code):
    p1 = struct.pack("B", (1 << 3) | 2) + struct.pack("B", len(email)) + email.encode("utf-8")
    p2 = struct.pack("B", (2 << 3) | 2) + struct.pack("B", len(code)) + code.encode("utf-8")
    payload = p1 + p2
    return b"\x00" + struct.pack(">I", len(payload)) + payload


def _emit(emit: Optional[Callable[[str, str], None]], level: str, message: str):
    if emit is None:
        print(message)
        return
    emit(level, message)


def extract_signup_bootstrap(*, html: str, js_bodies: Sequence[str], runtime: RuntimeContext) -> StageResult:
    site_key_match = re.search(r'sitekey":"(0x4[a-zA-Z0-9_-]+)"', html)
    if site_key_match:
        runtime.site_key = site_key_match.group(1)

    state_tree_match = re.search(r'next-router-state-tree":"([^"]+)"', html)
    if state_tree_match:
        runtime.state_tree = state_tree_match.group(1)

    for js_body in js_bodies:
        action_match = re.search(r"7f[a-fA-F0-9]{40}", js_body)
        if action_match:
            runtime.action_id = action_match.group(0)
            break

    if not runtime.action_id:
        return StageResult(False, "scan_bootstrap", ErrorType.PARSE, False, "未找到 Action ID")
    return StageResult(True, "scan_bootstrap")


def scan_signup_bootstrap(runtime: RuntimeContext, proxies, *, site_url: str = DEFAULT_SITE_URL) -> StageResult:
    started_at = time.perf_counter()
    try:
        with requests.Session(impersonate=DEFAULT_IMPERSONATE, proxies=proxies or None) as session:
            html = session.get(f"{site_url}/sign-up", timeout=30).text
            soup = BeautifulSoup(html, "html.parser")
            js_urls = [
                urljoin(f"{site_url}/sign-up", script["src"])
                for script in soup.find_all("script", src=True)
                if "_next/static" in script["src"]
            ]
            js_bodies = [session.get(js_url, timeout=30).text for js_url in js_urls]
        result = extract_signup_bootstrap(html=html, js_bodies=js_bodies, runtime=runtime)
        result.latency_ms = int((time.perf_counter() - started_at) * 1000)
        return result
    except Exception as exc:
        return StageResult(
            False,
            "scan_bootstrap",
            ErrorType.NETWORK,
            True,
            str(exc),
            latency_ms=int((time.perf_counter() - started_at) * 1000),
        )


def send_email_code_grpc(session, email, *, site_url: str = DEFAULT_SITE_URL, display_email: Optional[str] = None, emit=None) -> bool:
    url = f"{site_url}/auth_mgmt.AuthManagement/CreateEmailValidationCode"
    data = encode_grpc_message(1, email)
    headers = {
        "content-type": "application/grpc-web+proto",
        "x-grpc-web": "1",
        "x-user-agent": "connect-es/2.1.1",
        "origin": site_url,
        "referer": f"{site_url}/sign-up?redirect=grok-com",
    }
    shown_email = display_email or email
    try:
        response = session.post(url, data=data, headers=headers, timeout=30)
        if response.status_code != 200:
            _emit(
                emit,
                "warning",
                f"[!] {shown_email} 发送验证码响应异常: http={response.status_code}, grpc={response.headers.get('grpc-status')}, body={compact_text(response.text)}",
            )
        return response.status_code == 200
    except Exception as exc:
        _emit(emit, "warning", f"[-] {shown_email} 发送验证码异常: {exc}")
        return False


def request_and_wait_for_email_code(
    session,
    email_service,
    email,
    max_request_rounds=EMAIL_CODE_REQUEST_ROUNDS,
    poll_attempts_per_round=EMAIL_CODE_POLL_ATTEMPTS_PER_ROUND,
    excluded_codes=None,
    *,
    display_email: Optional[str] = None,
    emit=None,
    site_url: str = DEFAULT_SITE_URL,
    send_func=None,
):
    shown_email = display_email or email
    send = send_func or send_email_code_grpc
    for round_index in range(1, max_request_rounds + 1):
        sent = send(
            session,
            email,
            site_url=site_url,
            display_email=shown_email,
            emit=emit,
        )
        _emit(emit, "info", f"[*] {shown_email} 发码轮次 {round_index}/{max_request_rounds} {'已提交' if sent else '请求未确认成功'}，开始查收验证码...")
        verify_code = email_service.fetch_verification_code(email, max_attempts=poll_attempts_per_round, exclude_codes=excluded_codes)
        if verify_code:
            masked = verify_code[:2] + ("*" * max(0, len(verify_code) - 4)) + verify_code[-2:] if len(verify_code) > 4 else verify_code
            _emit(emit, "info", f"[+] {shown_email} 在第 {round_index} 轮收到验证码")
            _emit(emit, "info", f"[*] {shown_email} 本轮验证码: {masked} (len={len(verify_code)})")
            return verify_code
        if round_index < max_request_rounds:
            _emit(emit, "info", f"[*] {shown_email} 第 {round_index} 轮 3 分钟内未收到验证码，准备重发...")
    _emit(emit, "warning", f"[-] {shown_email} 连续 {max_request_rounds} 轮均未收到验证码")
    return None


def verify_email_code_grpc(session, email, code, *, site_url: str = DEFAULT_SITE_URL, display_email: Optional[str] = None, emit=None) -> bool:
    url = f"{site_url}/auth_mgmt.AuthManagement/VerifyEmailValidationCode"
    data = encode_grpc_message_verify(email, code)
    headers = {
        "content-type": "application/grpc-web+proto",
        "x-grpc-web": "1",
        "x-user-agent": "connect-es/2.1.1",
        "origin": site_url,
        "referer": f"{site_url}/sign-up?redirect=grok-com",
    }
    shown_email = display_email or email
    try:
        response = session.post(url, data=data, headers=headers, timeout=30)
        grpc_status = response.headers.get("grpc-status")
        body = (response.text or "").lower()
        ok = (
            response.status_code == 200
            and grpc_status in (None, "0")
            and "invalid-validation-code" not in body
            and "email validation code is invalid" not in body
            and '"error"' not in body
        )
        if not ok:
            _emit(
                emit,
                "warning",
                f"[!] {shown_email} 验证验证码失败: http={response.status_code}, grpc={grpc_status}, body={compact_text(response.text)}",
            )
        return ok
    except Exception as exc:
        _emit(emit, "warning", f"[-] {shown_email} 验证验证码异常: {exc}")
        return False
