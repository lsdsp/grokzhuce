import argparse
import concurrent.futures
import json
import logging
import os
import random
import re
import string
import struct
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests
from dotenv import load_dotenv

from g import EmailService, NsfwSettingsService, TurnstileService, UserAgreementService
from g.proxy_utils import build_requests_proxies

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

LOGGER = logging.getLogger("grok")
if not LOGGER.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    LOGGER.addHandler(_h)
LOGGER.setLevel(logging.INFO)

site_url = "https://accounts.x.ai"
DEFAULT_IMPERSONATE = "chrome120"
CHROME_PROFILES = [
    {"impersonate": "chrome110", "version": "110.0.0.0", "brand": "chrome"},
    {"impersonate": "chrome119", "version": "119.0.0.0", "brand": "chrome"},
    {"impersonate": "chrome120", "version": "120.0.0.0", "brand": "chrome"},
    {"impersonate": "edge99", "version": "99.0.1150.36", "brand": "edge"},
    {"impersonate": "edge101", "version": "101.0.1210.47", "brand": "edge"},
]
PROXIES = build_requests_proxies(preferred_keys=("GROK_PROXY_URL",))

config = {
    "site_key": "0x4AAAAAAAhr9JGVDZbrZOo0",
    "action_id": None,
    "state_tree": (
        "%5B%22%22%2C%7B%22children%22%3A%5B%22(app)%22%2C%7B%22children%22%3A%5B%22(auth)%22"
        "%2C%7B%22children%22%3A%5B%22sign-up%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D"
        "%2C%22%2Fsign-up%22%2C%22refresh%22%5D%7D%5D%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%5D%7D"
        "%2Cnull%2Cnull%2Ctrue%5D"
    ),
}

# legacy globals kept for compatibility/tests
post_lock = threading.Lock()
file_lock = threading.Lock()
attempt_lock = threading.Lock()
success_count = 0
attempt_count = 0
start_time = time.time()
target_count = 100
max_attempts = 0
stop_event = threading.Event()
attempt_limit_reached = threading.Event()
output_file = None

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


def read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


KEEP_SUCCESS_EMAIL = read_bool_env("KEEP_SUCCESS_EMAIL", False)


def should_delete_email_after_registration(registration_succeeded: bool, keep_success_email=None) -> bool:
    if keep_success_email is None:
        keep_success_email = KEEP_SUCCESS_EMAIL
    return (not registration_succeeded) or (not keep_success_email)


def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        return f"{local[:1]}*@{domain}"
    return f"{local[:2]}***{local[-1]}@{domain}"


class ErrorType(str, Enum):
    NONE = "none"
    NETWORK = "network"
    TIMEOUT = "timeout"
    CAPTCHA = "captcha"
    PARSE = "parse"
    SIGNUP = "signup"
    DEPENDENCY = "dependency"
    POLICY = "policy"
    UNKNOWN = "unknown"


class StopReason(str, Enum):
    TARGET_REACHED = "target_reached"
    ATTEMPT_LIMIT = "attempt_limit"
    EXTERNAL_STOP = "external_stop"


@dataclass(frozen=True)
class AppConfig:
    thread_count: int
    target_count: int
    max_attempts: int
    keep_success_email: bool
    output_file: str
    proxies: Dict[str, str]
    metrics_path: str


@dataclass
class RuntimeContext:
    site_key: str
    action_id: Optional[str]
    state_tree: str


@dataclass
class StageResult:
    ok: bool
    stage: str
    error_type: ErrorType = ErrorType.NONE
    retryable: bool = False
    details: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    latency_ms: Optional[int] = None


@dataclass
class AttemptClaim:
    allowed: bool
    slot_no: int
    reason: Optional[StopReason] = None


class JsonlLogger:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def event(self, level: str, stage: str, message: str, **fields: Any):
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "stage": stage,
            "message": message,
            **fields,
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


class StopPolicy:
    def __init__(self, target_count: int, max_attempts: int):
        self.target_count = max(1, int(target_count))
        self.max_attempts = max(1, int(max_attempts))
        self.success_count = 0
        self.attempt_count = 0
        self.stop_event = threading.Event()
        self.stop_reason: Optional[StopReason] = None
        self._lock = threading.Lock()

    def claim_attempt_slot(self) -> AttemptClaim:
        with self._lock:
            if self.stop_event.is_set():
                return AttemptClaim(False, self.attempt_count, self.stop_reason)
            if self.attempt_count >= self.max_attempts:
                self.stop_reason = StopReason.ATTEMPT_LIMIT
                self.stop_event.set()
                return AttemptClaim(False, self.attempt_count, self.stop_reason)
            self.attempt_count += 1
            return AttemptClaim(True, self.attempt_count, None)

    def mark_success(self) -> int:
        with self._lock:
            self.success_count += 1
            if self.success_count >= self.target_count:
                self.stop_reason = StopReason.TARGET_REACHED
                self.stop_event.set()
            return self.success_count

    def should_stop(self) -> bool:
        return self.stop_event.is_set()


def compute_effective_max_attempts(target: int, max_attempts_arg=None) -> int:
    target = max(1, int(target))
    if max_attempts_arg is None:
        return max(target * 4, target + 10)
    try:
        provided = int(max_attempts_arg)
    except Exception:
        provided = 1
    return max(1, provided)


def reset_runtime_state():
    global success_count, attempt_count, start_time
    success_count = 0
    attempt_count = 0
    start_time = time.time()
    stop_event.clear()
    attempt_limit_reached.clear()


def claim_attempt_slot():
    global attempt_count
    with attempt_lock:
        if stop_event.is_set():
            return None
        if max_attempts > 0 and attempt_count >= max_attempts:
            attempt_limit_reached.set()
            stop_event.set()
            return None
        attempt_count += 1
        return attempt_count


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


def send_email_code_grpc(session, email):
    url = f"{site_url}/auth_mgmt.AuthManagement/CreateEmailValidationCode"
    data = encode_grpc_message(1, email)
    headers = {
        "content-type": "application/grpc-web+proto",
        "x-grpc-web": "1",
        "x-user-agent": "connect-es/2.1.1",
        "origin": site_url,
        "referer": f"{site_url}/sign-up?redirect=grok-com",
    }
    try:
        res = session.post(url, data=data, headers=headers, timeout=30)
        if res.status_code != 200:
            print(f"[!] {email} 发送验证码响应异常: http={res.status_code}, grpc={res.headers.get('grpc-status')}, body={compact_text(res.text)}")
        return res.status_code == 200
    except Exception as e:
        print(f"[-] {email} 发送验证码异常: {e}")
        return False


def request_and_wait_for_email_code(
    session,
    email_service,
    email,
    max_request_rounds=EMAIL_CODE_REQUEST_ROUNDS,
    poll_attempts_per_round=EMAIL_CODE_POLL_ATTEMPTS_PER_ROUND,
    excluded_codes=None,
):
    for round_index in range(1, max_request_rounds + 1):
        sent = send_email_code_grpc(session, email)
        print(f"[*] {email} 发码轮次 {round_index}/{max_request_rounds} {'已提交' if sent else '请求未确认成功'}，开始查收验证码...")
        verify_code = email_service.fetch_verification_code(email, max_attempts=poll_attempts_per_round, exclude_codes=excluded_codes)
        if verify_code:
            masked = verify_code[:2] + ("*" * max(0, len(verify_code) - 4)) + verify_code[-2:] if len(verify_code) > 4 else verify_code
            print(f"[+] {email} 在第 {round_index} 轮收到验证码")
            print(f"[*] {email} 本轮验证码: {masked} (len={len(verify_code)})")
            return verify_code
        if round_index < max_request_rounds:
            print(f"[*] {email} 第 {round_index} 轮 3 分钟内未收到验证码，准备重发...")
    print(f"[-] {email} 连续 {max_request_rounds} 轮均未收到验证码")
    return None


def verify_email_code_grpc(session, email, code):
    url = f"{site_url}/auth_mgmt.AuthManagement/VerifyEmailValidationCode"
    data = encode_grpc_message_verify(email, code)
    headers = {
        "content-type": "application/grpc-web+proto",
        "x-grpc-web": "1",
        "x-user-agent": "connect-es/2.1.1",
        "origin": site_url,
        "referer": f"{site_url}/sign-up?redirect=grok-com",
    }
    try:
        res = session.post(url, data=data, headers=headers, timeout=30)
        grpc_status = res.headers.get("grpc-status")
        body = (res.text or "").lower()
        ok = res.status_code == 200 and grpc_status in (None, "0") and "invalid-validation-code" not in body and "email validation code is invalid" not in body and '"error"' not in body
        if not ok:
            print(f"[!] {email} 验证验证码失败: http={res.status_code}, grpc={grpc_status}, body={compact_text(res.text)}")
        return ok
    except Exception as e:
        print(f"[-] {email} 验证验证码异常: {e}")
        return False


class GrokRunner:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.runtime = RuntimeContext(config["site_key"], config["action_id"], config["state_tree"])
        self.stop = StopPolicy(cfg.target_count, cfg.max_attempts)
        self.metrics = JsonlLogger(cfg.metrics_path)
        self.post_lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.error_counts: Dict[str, int] = {}
        self.start_ts = time.time()
        Path(cfg.output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(cfg.output_file).touch(exist_ok=True)
        try:
            os.chmod(cfg.output_file, 0o600)
        except Exception:
            pass

    def _log(self, level: str, stage: str, message: str, **fields: Any):
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        self.metrics.event(level, stage, message, **fields)
        getattr(LOGGER, level.lower() if hasattr(LOGGER, level.lower()) else "info")(message)

    def _fail(self, r: StageResult, thread_id: int, attempt_no: int, email: str = ""):
        self.error_counts[r.error_type.value] = self.error_counts.get(r.error_type.value, 0) + 1
        self._log("warning" if r.retryable else "error", r.stage, f"{r.stage} failed", thread_id=thread_id, attempt_no=attempt_no, email=mask_email(email), error_type=r.error_type.value, details=compact_text(r.details))

    def scan_bootstrap(self) -> StageResult:
        st = time.perf_counter()
        try:
            with requests.Session(impersonate=DEFAULT_IMPERSONATE, proxies=self.cfg.proxies or None) as s:
                html = s.get(f"{site_url}/sign-up", timeout=30).text
                m = re.search(r'sitekey":"(0x4[a-zA-Z0-9_-]+)"', html)
                if m:
                    self.runtime.site_key = m.group(1)
                t = re.search(r'next-router-state-tree":"([^"]+)"', html)
                if t:
                    self.runtime.state_tree = t.group(1)
                soup = BeautifulSoup(html, "html.parser")
                js_urls = [urljoin(f"{site_url}/sign-up", x["src"]) for x in soup.find_all("script", src=True) if "_next/static" in x["src"]]
                for js_url in js_urls:
                    js = s.get(js_url, timeout=30).text
                    hit = re.search(r"7f[a-fA-F0-9]{40}", js)
                    if hit:
                        self.runtime.action_id = hit.group(0)
                        break
            if not self.runtime.action_id:
                return StageResult(False, "scan_bootstrap", ErrorType.PARSE, False, "未找到 Action ID", latency_ms=int((time.perf_counter() - st) * 1000))
            config.update({"site_key": self.runtime.site_key, "state_tree": self.runtime.state_tree, "action_id": self.runtime.action_id})
            return StageResult(True, "scan_bootstrap", latency_ms=int((time.perf_counter() - st) * 1000))
        except Exception as e:
            return StageResult(False, "scan_bootstrap", ErrorType.NETWORK, True, str(e), latency_ms=int((time.perf_counter() - st) * 1000))

    def worker(self, thread_id: int):
        time.sleep(random.uniform(0, 5))
        try:
            email_svc = EmailService()
            ts_svc = TurnstileService()
            tos_svc = UserAgreementService()
            nsfw_svc = NsfwSettingsService()
        except Exception as e:
            self._log("error", "bootstrap_thread", f"[T{thread_id}] 服务初始化失败: {e}", thread_id=thread_id, error_type=ErrorType.DEPENDENCY.value)
            return

        while not self.stop.should_stop():
            claim = self.stop.claim_attempt_slot()
            if not claim.allowed:
                break
            attempt_no = claim.slot_no
            if attempt_no <= 3 or attempt_no % 20 == 0:
                self._log("info", "attempt", f"[T{thread_id}] 全局尝试进度: {attempt_no}/{self.stop.max_attempts}", attempt_no=attempt_no, thread_id=thread_id)

            current_email = ""
            success = False
            try:
                imp, ua = get_random_chrome_profile()
                with requests.Session(impersonate=imp, proxies=self.cfg.proxies or None) as sess:
                    try:
                        sess.get(site_url, timeout=10)
                    except Exception:
                        pass
                    try:
                        _jwt, email = email_svc.create_email()
                    except Exception as e:
                        self._fail(StageResult(False, "create_identity", ErrorType.DEPENDENCY, True, str(e)), thread_id, attempt_no)
                        time.sleep(5)
                        continue
                    if not email:
                        self._fail(StageResult(False, "create_identity", ErrorType.DEPENDENCY, True, "创建邮箱失败"), thread_id, attempt_no)
                        time.sleep(5)
                        continue
                    current_email = email
                    password = generate_random_string()
                    used_codes = set()
                    for _ in range(MAX_EMAIL_CODE_CYCLES_PER_EMAIL):
                        code = request_and_wait_for_email_code(sess, email_svc, email, excluded_codes=used_codes)
                        if not code:
                            self._fail(StageResult(False, "request_code", ErrorType.TIMEOUT, True, "未收到验证码"), thread_id, attempt_no, email)
                            break
                        if not verify_email_code_grpc(sess, email, code):
                            used_codes.add(code)
                            self._fail(StageResult(False, "verify_code", ErrorType.SIGNUP, True, "验证码校验失败"), thread_id, attempt_no, email)
                            continue
                        signup_ok = False
                        code_invalid = False
                        sso = ""
                        sso_rw = ""
                        for _ in range(SIGNUP_RETRY_PER_CODE):
                            task_id = ts_svc.create_task(site_url, self.runtime.site_key)
                            token = ts_svc.get_response(task_id)
                            if not token or token == "CAPTCHA_FAIL":
                                continue
                            headers = {
                                "user-agent": ua,
                                "accept": "text/x-component",
                                "content-type": "text/plain;charset=UTF-8",
                                "origin": site_url,
                                "referer": f"{site_url}/sign-up",
                                "cookie": f"__cf_bm={sess.cookies.get('__cf_bm', '')}",
                                "next-router-state-tree": self.runtime.state_tree,
                                "next-action": self.runtime.action_id,
                            }
                            payload = [{
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
                            }]
                            with self.post_lock:
                                res = sess.post(f"{site_url}/sign-up", json=payload, headers=headers, timeout=45)
                            body = (res.text or "").lower()
                            if "invalid-validation-code" in body or "email validation code is invalid" in body:
                                code_invalid = True
                                used_codes.add(code)
                                break
                            if res.status_code != 200:
                                time.sleep(3)
                                continue
                            hit = re.search(r'(https://[^" \s]+set-cookie\?q=[^:" \s]+)1:', res.text)
                            if not hit:
                                break
                            back = sess.get(hit.group(1), allow_redirects=True, timeout=30)
                            _ = back.status_code
                            sso = sess.cookies.get("sso") or ""
                            sso_rw = sess.cookies.get("sso-rw") or ""
                            if not sso:
                                break
                            signup_ok = True
                            break
                        if code_invalid:
                            self._log("warning", "signup", f"[T{thread_id}] 注册阶段返回验证码失效，准备重新发码", thread_id=thread_id, attempt_no=attempt_no, email=mask_email(email), error_type=ErrorType.SIGNUP.value)
                            continue
                        if not signup_ok:
                            self._fail(StageResult(False, "signup", ErrorType.SIGNUP, True, "注册重试耗尽"), thread_id, attempt_no, email)
                            break
                        tos = tos_svc.accept_tos_version(sso=sso, sso_rw=sso_rw or "", impersonate=imp, user_agent=ua)
                        if not tos.get("ok") or not tos.get("hex_reply"):
                            self._fail(StageResult(False, "post_signup_actions", ErrorType.SIGNUP, False, "TOS 失败"), thread_id, attempt_no, email)
                            break
                        nsfw = nsfw_svc.enable_nsfw(sso=sso, sso_rw=sso_rw or "", impersonate=imp, user_agent=ua)
                        if not nsfw.get("ok") or not nsfw.get("hex_reply"):
                            self._fail(StageResult(False, "post_signup_actions", ErrorType.SIGNUP, False, "NSFW 失败"), thread_id, attempt_no, email)
                            break
                        unhinged = nsfw_svc.enable_unhinged(sso=sso, sso_rw=sso_rw or "", impersonate=imp, user_agent=ua)
                        nsfw_tag = "OK"
                        if not unhinged.get("supported", True):
                            nsfw_tag = "SKIP"
                        elif not unhinged.get("ok", False):
                            nsfw_tag = "WARN"
                        with self.write_lock:
                            with open(self.cfg.output_file, "a", encoding="utf-8") as f:
                                f.write(sso + "\n")
                            done = self.stop.mark_success()
                            avg = (time.time() - self.start_ts) / max(1, done)
                        self._log("info", "record_success", f"[T{thread_id}] 注册成功: {done}/{self.stop.target_count} | {mask_email(email)} | 平均: {avg:.1f}s | NSFW: {nsfw_tag}", thread_id=thread_id, attempt_no=attempt_no, email=mask_email(email))
                        success = True
                        break
            except Exception as e:
                self._log("error", "worker_exception", f"[T{thread_id}] 线程异常: {compact_text(e)}", thread_id=thread_id, attempt_no=attempt_no, error_type=ErrorType.UNKNOWN.value)
                time.sleep(5)
            finally:
                if current_email:
                    if should_delete_email_after_registration(success, self.cfg.keep_success_email):
                        try:
                            email_svc.delete_email(current_email)
                        except Exception:
                            pass
                    else:
                        self._log("info", "cleanup", f"[T{thread_id}] 保留成功邮箱: {mask_email(current_email)}", thread_id=thread_id, attempt_no=attempt_no, email=mask_email(current_email))
            if not success:
                time.sleep(5)

    def run(self) -> int:
        self._log("info", "startup", "正在初始化...", metrics_path=self.cfg.metrics_path)
        self._log("info", "startup", f"当前代理: {self.cfg.proxies.get('https') if self.cfg.proxies else '直连'}")
        self._log("info", "startup", f"成功后保留邮箱: {'ON' if self.cfg.keep_success_email else 'OFF'}")
        boot = self.scan_bootstrap()
        if not boot.ok:
            self._fail(boot, thread_id=0, attempt_no=0)
            return 1
        self._log("info", "scan_bootstrap", f"Action ID: {self.runtime.action_id}", latency_ms=boot.latency_ms)
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.cfg.thread_count) as ex:
            futures = [ex.submit(self.worker, i + 1) for i in range(self.cfg.thread_count)]
            for f in concurrent.futures.as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    self._log("error", "executor", f"worker future 异常: {e}", error_type=ErrorType.UNKNOWN.value)
        self._log("info", "summary", f"运行结束: success={self.stop.success_count}/{self.stop.target_count}, attempts={self.stop.attempt_count}/{self.stop.max_attempts}, stop_reason={self.stop.stop_reason.value if self.stop.stop_reason else 'n/a'}")
        for k, v in sorted(self.error_counts.items(), key=lambda x: x[1], reverse=True):
            self._log("info", "summary", f"failure_bucket {k}={v}")
        if self.stop.stop_reason == StopReason.ATTEMPT_LIMIT and self.stop.success_count < self.stop.target_count:
            self._log("warning", "summary", "已达到最大尝试上限，提前停止。 [ATTEMPT_LIMIT_REACHED]", error_type=ErrorType.POLICY.value)
        return 0


def register_single_thread():
    raise RuntimeError("register_single_thread 已弃用，请通过 main()/GrokRunner.run() 启动。")


def main(thread_count=None, total_count=None, max_attempts_arg=None, metrics_file=None):
    print("=" * 60 + "\nGrok 注册机\n" + "=" * 60)
    if thread_count is None:
        try:
            t = int(input("\n并发数 (默认8): ").strip() or 8)
        except Exception:
            t = 8
    else:
        t = int(thread_count)
    if total_count is None:
        try:
            total = int(input("注册数量 (默认100): ").strip() or 100)
        except Exception:
            total = 100
    else:
        total = int(total_count)

    t = max(1, t)
    total = max(1, total)
    eff = compute_effective_max_attempts(total, max_attempts_arg)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("keys", exist_ok=True)
    os.makedirs("logs/grok", exist_ok=True)
    out = f"keys/grok_{ts}_{total}.txt"
    metrics = metrics_file or f"logs/grok/metrics.{ts}.jsonl"

    cfg = AppConfig(
        thread_count=t,
        target_count=total,
        max_attempts=eff,
        keep_success_email=KEEP_SUCCESS_EMAIL,
        output_file=out,
        proxies=PROXIES,
        metrics_path=metrics,
    )

    global target_count, max_attempts, output_file, success_count, attempt_count
    target_count = total
    max_attempts = eff
    output_file = out
    reset_runtime_state()

    print(f"[*] 启动 {t} 个线程，目标 {total} 个")
    print(f"[*] 最大尝试上限: {eff}")
    if max_attempts_arg is None:
        print(f"[*] 未指定 --max-attempts，自动使用 {eff}。如网络不稳定可手动调整（例如 --max-attempts {total * 4}）。")

    runner = GrokRunner(cfg)
    code = runner.run()
    success_count = runner.stop.success_count
    attempt_count = runner.stop.attempt_count
    if runner.stop.stop_reason == StopReason.ATTEMPT_LIMIT:
        attempt_limit_reached.set()
        stop_event.set()
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grok batch registration")
    parser.add_argument("--threads", type=int, default=None, help="并发数")
    parser.add_argument("--count", type=int, default=None, help="注册数量")
    parser.add_argument("--max-attempts", type=int, default=None, help="最大尝试次数（默认按 count 自动计算）")
    parser.add_argument("--metrics-file", type=str, default=None, help="结构化指标日志输出路径（JSONL）")
    args = parser.parse_args()
    raise SystemExit(main(thread_count=args.threads, total_count=args.count, max_attempts_arg=args.max_attempts, metrics_file=args.metrics_file))
