import struct
from typing import Optional

from grok_config import DEFAULT_SITE_URL
from grok_protocol_common import compact_text, emit_log


EMAIL_CODE_REQUEST_ROUNDS = 3
EMAIL_CODE_POLL_ATTEMPTS_PER_ROUND = 180
MAX_EMAIL_CODE_CYCLES_PER_EMAIL = 3


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
            emit_log(
                emit,
                "warning",
                f"[!] {shown_email} 发送验证码响应异常: http={response.status_code}, grpc={response.headers.get('grpc-status')}, body={compact_text(response.text)}",
            )
        return response.status_code == 200
    except Exception as exc:
        emit_log(emit, "warning", f"[-] {shown_email} 发送验证码异常: {exc}")
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
        emit_log(emit, "info", f"[*] {shown_email} 发码轮次 {round_index}/{max_request_rounds} {'已提交' if sent else '请求未确认成功'}，开始查收验证码...")
        verify_code = email_service.fetch_verification_code(
            email,
            max_attempts=poll_attempts_per_round,
            exclude_codes=excluded_codes,
        )
        if verify_code:
            masked = verify_code[:2] + ("*" * max(0, len(verify_code) - 4)) + verify_code[-2:] if len(verify_code) > 4 else verify_code
            emit_log(emit, "info", f"[+] {shown_email} 在第 {round_index} 轮收到验证码")
            emit_log(emit, "info", f"[*] {shown_email} 本轮验证码: {masked} (len={len(verify_code)})")
            return verify_code
        if round_index < max_request_rounds:
            emit_log(emit, "info", f"[*] {shown_email} 第 {round_index} 轮 3 分钟内未收到验证码，准备重发...")
    emit_log(emit, "warning", f"[-] {shown_email} 连续 {max_request_rounds} 轮均未收到验证码")
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
            emit_log(
                emit,
                "warning",
                f"[!] {shown_email} 验证验证码失败: http={response.status_code}, grpc={grpc_status}, body={compact_text(response.text)}",
            )
        return ok
    except Exception as exc:
        emit_log(emit, "warning", f"[-] {shown_email} 验证验证码异常: {exc}")
        return False
