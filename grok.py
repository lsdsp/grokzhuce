import os, json, random, string, time, re, struct, argparse
import threading
import concurrent.futures
from pathlib import Path
from urllib.parse import urljoin, urlparse
from curl_cffi import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from g import EmailService, TurnstileService, UserAgreementService, NsfwSettingsService
from g.proxy_utils import build_requests_proxies

# 显式按项目根目录加载 .env，避免从其他工作目录启动时配置丢失。
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

# 基础配置
site_url = "https://accounts.x.ai"
DEFAULT_IMPERSONATE = "chrome120"
CHROME_PROFILES = [
    {"impersonate": "chrome110", "version": "110.0.0.0", "brand": "chrome"},
    {"impersonate": "chrome119", "version": "119.0.0.0", "brand": "chrome"},
    {"impersonate": "chrome120", "version": "120.0.0.0", "brand": "chrome"},
    {"impersonate": "edge99", "version": "99.0.1150.36", "brand": "edge"},
    {"impersonate": "edge101", "version": "101.0.1210.47", "brand": "edge"},
]
def get_random_chrome_profile():
    profile = random.choice(CHROME_PROFILES)
    if profile.get("brand") == "edge":
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
PROXIES = build_requests_proxies(preferred_keys=("GROK_PROXY_URL",))

# 动态获取的全局变量
config = {
    "site_key": "0x4AAAAAAAhr9JGVDZbrZOo0",
    "action_id": None,
    "state_tree": "%5B%22%22%2C%7B%22children%22%3A%5B%22(app)%22%2C%7B%22children%22%3A%5B%22(auth)%22%2C%7B%22children%22%3A%5B%22sign-up%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2Fsign-up%22%2C%22refresh%22%5D%7D%5D%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%2Ctrue%5D"
}

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
EMAIL_CODE_POLL_ATTEMPTS_PER_ROUND = 180  # 3分钟（按 fetch_verification_code 每秒轮询一次）
MAX_EMAIL_CODE_CYCLES_PER_EMAIL = 3


def compact_text(value, max_len=220):
    """压缩日志文本，避免打印过长响应。"""
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def read_bool_env(name: str, default: bool) -> bool:
    """Read bool env with tolerant true/false parsing."""
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


def should_delete_email_after_registration(
    registration_succeeded: bool, keep_success_email=None
) -> bool:
    """Delete failed emails always; keep successful emails when configured."""
    if keep_success_email is None:
        keep_success_email = KEEP_SUCCESS_EMAIL
    return (not registration_succeeded) or (not keep_success_email)


def compute_effective_max_attempts(target: int, max_attempts_arg=None) -> int:
    """Return a bounded global attempt budget for this run."""
    target = max(1, int(target))
    if max_attempts_arg is None:
        # Default to a retry-friendly but finite budget in unstable networks.
        return max(target * 4, target + 10)
    try:
        provided = int(max_attempts_arg)
    except Exception:
        provided = 1
    return max(1, provided)


def reset_runtime_state():
    """Reset mutable runtime globals for a fresh run."""
    global success_count, attempt_count, start_time
    success_count = 0
    attempt_count = 0
    start_time = time.time()
    stop_event.clear()
    attempt_limit_reached.clear()


def claim_attempt_slot():
    """Claim one global account-attempt slot, or return None when exhausted."""
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
    return random.choice(string.ascii_uppercase) + ''.join(random.choice(string.ascii_lowercase) for _ in range(length - 1))

def generate_random_string(length: int = 15) -> str:
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))

def encode_grpc_message(field_id, string_value):
    key = (field_id << 3) | 2
    value_bytes = string_value.encode('utf-8')
    length = len(value_bytes)
    payload = struct.pack('B', key) + struct.pack('B', length) + value_bytes
    return b'\x00' + struct.pack('>I', len(payload)) + payload

def encode_grpc_message_verify(email, code):
    p1 = struct.pack('B', (1 << 3) | 2) + struct.pack('B', len(email)) + email.encode('utf-8')
    p2 = struct.pack('B', (2 << 3) | 2) + struct.pack('B', len(code)) + code.encode('utf-8')
    payload = p1 + p2
    return b'\x00' + struct.pack('>I', len(payload)) + payload

def send_email_code_grpc(session, email):
    url = f"{site_url}/auth_mgmt.AuthManagement/CreateEmailValidationCode"
    data = encode_grpc_message(1, email)
    headers = {"content-type": "application/grpc-web+proto", "x-grpc-web": "1", "x-user-agent": "connect-es/2.1.1", "origin": site_url, "referer": f"{site_url}/sign-up?redirect=grok-com"}
    try:
        # print(f"[debug] {email} 正在发送验证码请求...")
        res = session.post(url, data=data, headers=headers, timeout=30)
        # print(f"[debug] {email} 请求结束，状态码: {res.status_code}")
        if res.status_code != 200:
            grpc_status = res.headers.get("grpc-status")
            print(
                f"[!] {email} 发送验证码响应异常: http={res.status_code}, grpc={grpc_status}, "
                f"body={compact_text(res.text)}"
            )
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
    """
    先请求验证码（不依赖请求返回是否成功），再轮询邮箱是否收到验证码。
    每轮轮询窗口：poll_attempts_per_round 秒；最多重试 max_request_rounds 轮。
    """
    for round_index in range(1, max_request_rounds + 1):
        sent = send_email_code_grpc(session, email)
        if sent:
            print(f"[*] {email} 发码轮次 {round_index}/{max_request_rounds} 已提交，开始查收验证码...")
        else:
            print(f"[!] {email} 发码轮次 {round_index}/{max_request_rounds} 请求未确认成功，仍开始查收验证码...")

        verify_code = email_service.fetch_verification_code(
            email,
            max_attempts=poll_attempts_per_round,
            exclude_codes=excluded_codes,
        )
        if verify_code:
            if len(verify_code) > 4:
                masked = verify_code[:2] + ("*" * (len(verify_code) - 4)) + verify_code[-2:]
            else:
                masked = verify_code
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
    headers = {"content-type": "application/grpc-web+proto", "x-grpc-web": "1", "x-user-agent": "connect-es/2.1.1", "origin": site_url, "referer": f"{site_url}/sign-up?redirect=grok-com"}
    try:
        res = session.post(url, data=data, headers=headers, timeout=30)
        grpc_status = res.headers.get("grpc-status")
        body_text = (res.text or "").lower()
        has_known_error = (
            "invalid-validation-code" in body_text
            or "email validation code is invalid" in body_text
            or '"error"' in body_text
        )
        ok = (
            res.status_code == 200
            and grpc_status in (None, "0")
            and not has_known_error
        )
        if not ok:
            print(
                f"[!] {email} 验证验证码失败: http={res.status_code}, grpc={grpc_status}, "
                f"body={compact_text(res.text)}"
            )
        return ok
    except Exception as e:
        print(f"[-] {email} 验证验证码异常: {e}")
        return False

def register_single_thread():
    # 错峰启动，防止瞬时并发过高
    time.sleep(random.uniform(0, 5))

    try:
        email_service = EmailService()
        turnstile_service = TurnstileService()
        user_agreement_service = UserAgreementService()
        nsfw_service = NsfwSettingsService()
    except Exception as e:
        print(f"[-] 服务初始化失败: {e}")
        return

    # 修正：直接从 config 获取
    final_action_id = config["action_id"]
    if not final_action_id:
        print("[-] 线程退出：缺少 Action ID")
        return

    current_email = None  # 追踪当前邮箱，确保异常时能删除

    while True:
        try:
            if stop_event.is_set():
                if current_email:
                    try: email_service.delete_email(current_email)
                    except: pass
                return

            slot_no = claim_attempt_slot()
            if slot_no is None:
                if current_email:
                    try: email_service.delete_email(current_email)
                    except: pass
                    current_email = None
                return
            if slot_no <= 3 or slot_no % 20 == 0:
                print(f"[*] 全局尝试进度: {slot_no}/{max_attempts}")

            impersonate_fingerprint, account_user_agent = get_random_chrome_profile()
            with requests.Session(impersonate=impersonate_fingerprint, proxies=PROXIES) as session:
                # 预热连接
                try: session.get(site_url, timeout=10)
                except: pass

                password = generate_random_string()

                try:
                    jwt, email = email_service.create_email()
                    current_email = email
                except Exception as e:
                    print(f"[-] 邮箱服务抛出异常: {e}")
                    jwt, email, current_email = None, None, None

                if not email:
                    print("[-] 创建邮箱失败：未获取到邮箱地址")
                    time.sleep(5); continue

                if stop_event.is_set():
                    email_service.delete_email(email)
                    current_email = None
                    return

                print(f"[*] 开始注册: {email}")

                registration_succeeded = False
                force_refresh_code = False
                used_verify_codes = set()

                # 单个邮箱最多进行若干轮“取码+校验+注册”
                for code_cycle in range(1, MAX_EMAIL_CODE_CYCLES_PER_EMAIL + 1):
                    if stop_event.is_set():
                        email_service.delete_email(email)
                        current_email = None
                        return

                    if force_refresh_code:
                        print(f"[*] {email} 检测到验证码失效，重新进入发码流程（循环 {code_cycle}/{MAX_EMAIL_CODE_CYCLES_PER_EMAIL}）")
                    force_refresh_code = False

                    # Step 1/2: 先发码（无需校验返回）再查码，3分钟窗口，最多3轮
                    verify_code = request_and_wait_for_email_code(
                        session=session,
                        email_service=email_service,
                        email=email,
                        excluded_codes=used_verify_codes,
                    )
                    if not verify_code:
                        print(f"[-] {email} 发码后未获取验证码，放弃本邮箱")
                        break

                    # Step 3: 验证验证码
                    if not verify_email_code_grpc(session, email, verify_code):
                        used_verify_codes.add(verify_code)
                        print(f"[-] {email} VerifyEmailValidationCode 未通过，准备重新发码")
                        continue

                    # Step 4: 注册重试循环
                    code_invalid_in_signup = False
                    for attempt in range(3):
                        attempt_no = attempt + 1
                        if stop_event.is_set():
                            email_service.delete_email(email)
                            current_email = None
                            return
                        task_id = turnstile_service.create_task(site_url, config["site_key"])
                        token = turnstile_service.get_response(task_id)

                        if not token or token == "CAPTCHA_FAIL":
                            print(f"[!] {email} 第 {attempt_no}/3 次 Turnstile 未拿到有效 token")
                            continue

                        headers = {
                            "user-agent": account_user_agent, "accept": "text/x-component", "content-type": "text/plain;charset=UTF-8",
                            "origin": site_url, "referer": f"{site_url}/sign-up", "cookie": f"__cf_bm={session.cookies.get('__cf_bm','')}",
                            "next-router-state-tree": config["state_tree"], "next-action": final_action_id
                        }
                        payload = [{
                            "emailValidationCode": verify_code,
                            "createUserAndSessionRequest": {
                                "email": email, "givenName": generate_random_name(), "familyName": generate_random_name(),
                                "clearTextPassword": password, "tosAcceptedVersion": "$undefined"
                            },
                            "turnstileToken": token, "promptOnDuplicateEmail": True
                        }]

                        with post_lock:
                            res = session.post(
                                f"{site_url}/sign-up",
                                json=payload,
                                headers=headers,
                                timeout=45,
                            )

                        if res.status_code == 200:
                            body_text = (res.text or "").lower()
                            if "invalid-validation-code" in body_text or "email validation code is invalid" in body_text:
                                used_verify_codes.add(verify_code)
                                print(
                                    f"[!] {email} 第 {attempt_no}/3 次 /sign-up 返回验证码无效，准备重新发码；"
                                    f"body={compact_text(res.text)}"
                                )
                                code_invalid_in_signup = True
                                break

                            match = re.search(r'(https://[^" \s]+set-cookie\?q=[^:" \s]+)1:', res.text)
                            if not match:
                                print(
                                    f"[!] {email} 第 {attempt_no}/3 次 /sign-up 后未提取到 set-cookie 链接，"
                                    f"body={compact_text(res.text)}"
                                )
                                break
                            if match:
                                verify_url = match.group(1)
                                verify_res = session.get(verify_url, allow_redirects=True, timeout=30)
                                sso = session.cookies.get("sso")
                                sso_rw = session.cookies.get("sso-rw")
                                if not sso:
                                    print(
                                        f"[!] {email} 第 {attempt_no}/3 次 set-cookie 回跳后未拿到 sso，"
                                        f"http={verify_res.status_code}, cookies={list(session.cookies.keys())}"
                                    )
                                    break

                                tos_result = user_agreement_service.accept_tos_version(
                                    sso=sso,
                                    sso_rw=sso_rw or "",
                                    impersonate=impersonate_fingerprint,
                                    user_agent=account_user_agent,
                                )
                                tos_hex = tos_result.get("hex_reply") or ""
                                if not tos_result.get("ok") or not tos_hex:
                                    print(
                                        f"[!] {email} TOS 同意失败: http={tos_result.get('status_code')}, "
                                        f"grpc={tos_result.get('grpc_status')}, error={tos_result.get('error')}, "
                                        f"hex_len={len(tos_hex)}"
                                    )
                                    break

                                nsfw_result = nsfw_service.enable_nsfw(
                                    sso=sso,
                                    sso_rw=sso_rw or "",
                                    impersonate=impersonate_fingerprint,
                                    user_agent=account_user_agent,
                                )
                                nsfw_hex = nsfw_result.get("hex_reply") or ""
                                if not nsfw_result.get("ok") or not nsfw_hex:
                                    print(
                                        f"[!] {email} NSFW 开关失败: http={nsfw_result.get('status_code')}, "
                                        f"grpc={nsfw_result.get('grpc_status')}, error={nsfw_result.get('error')}, "
                                        f"hex_len={len(nsfw_hex)}"
                                    )
                                    break

                                # 立即进行二次验证 (enable_unhinged)
                                unhinged_result = nsfw_service.enable_unhinged(
                                    sso=sso,
                                    sso_rw=sso_rw or "",
                                    impersonate=impersonate_fingerprint,
                                    user_agent=account_user_agent,
                                )
                                unhinged_ok = unhinged_result.get("ok", False)
                                unhinged_supported = unhinged_result.get("supported", True)
                                if not unhinged_ok and unhinged_supported:
                                    print(
                                        f"[!] {email} Unhinged 二次验证失败: "
                                        f"http={unhinged_result.get('status_code')}, "
                                        f"grpc={unhinged_result.get('grpc_status')}, "
                                        f"error={unhinged_result.get('error')}"
                                    )

                                with file_lock:
                                    global success_count
                                    if success_count >= target_count:
                                        if not stop_event.is_set():
                                            stop_event.set()
                                        print(f"[*] 已达到目标数量，结束当前邮箱流程: {email}")
                                        registration_succeeded = True
                                        break
                                    try:
                                        with open(output_file, "a") as f: f.write(sso + "\n")
                                    except Exception as write_err:
                                        print(f"[-] 写入文件失败: {write_err}")
                                        break
                                    success_count += 1
                                    avg = (time.time() - start_time) / success_count
                                    if not unhinged_supported:
                                        nsfw_tag = "SKIP"
                                    elif unhinged_ok:
                                        nsfw_tag = "OK"
                                    else:
                                        nsfw_tag = "WARN"
                                    print(f"[OK] 注册成功: {success_count}/{target_count} | {email} | SSO: {sso[:15]}... | 平均: {avg:.1f}s | NSFW: {nsfw_tag}")
                                    if success_count >= target_count and not stop_event.is_set():
                                        stop_event.set()
                                        print(f"[*] 已达到目标数量: {success_count}/{target_count}，停止新注册")
                                registration_succeeded = True
                                break  # 跳出 attempt 重试
                        else:
                            print(
                                f"[!] {email} 第 {attempt_no}/3 次 /sign-up 响应异常: "
                                f"http={res.status_code}, body={compact_text(res.text)}"
                            )

                        time.sleep(3)

                    if registration_succeeded:
                        break
                    if code_invalid_in_signup:
                        force_refresh_code = True
                        continue
                    print(f"[-] {email} 注册阶段重试 3 次均失败，放弃本邮箱")
                    break

                if should_delete_email_after_registration(registration_succeeded):
                    email_service.delete_email(email)
                else:
                    print(f"[KEEP] 注册成功后保留邮箱: {email}")
                current_email = None
                if not registration_succeeded:
                    time.sleep(5)

        except Exception as e:
            print(f"[-] 线程异常({type(e).__name__}): {str(e)[:120]}")
            # 异常时确保删除邮箱
            if current_email:
                try:
                    email_service.delete_email(current_email)
                except:
                    pass
                current_email = None
            time.sleep(5)

def main(thread_count=None, total_count=None, max_attempts_arg=None):
    print("=" * 60 + "\nGrok 注册机\n" + "=" * 60)
    
    # 1. 扫描参数
    print("[*] 正在初始化...")
    if PROXIES:
        print(f"[*] 当前代理: {PROXIES.get('https')}")
    else:
        print("[!] 未检测到代理配置，将使用直连")
    print(f"[*] 成功后保留邮箱: {'ON' if KEEP_SUCCESS_EMAIL else 'OFF'}")
    start_url = f"{site_url}/sign-up"
    with requests.Session(impersonate=DEFAULT_IMPERSONATE, proxies=PROXIES) as s:
        try:
            html = s.get(start_url, timeout=30).text
            # Key
            key_match = re.search(r'sitekey":"(0x4[a-zA-Z0-9_-]+)"', html)
            if key_match: config["site_key"] = key_match.group(1)
            # Tree
            tree_match = re.search(r'next-router-state-tree":"([^"]+)"', html)
            if tree_match: config["state_tree"] = tree_match.group(1)
            # Action ID
            soup = BeautifulSoup(html, 'html.parser')
            js_urls = [urljoin(start_url, script['src']) for script in soup.find_all('script', src=True) if '_next/static' in script['src']]
            for js_url in js_urls:
                js_content = s.get(js_url, timeout=30).text
                match = re.search(r'7f[a-fA-F0-9]{40}', js_content)
                if match:
                    config["action_id"] = match.group(0)
                    print(f"[+] Action ID: {config['action_id']}")
                    break
        except Exception as e:
            print(f"[-] 初始化扫描失败: {e}")
            return

    if not config["action_id"]:
        print("[-] 错误: 未找到 Action ID")
        return

    # 2. 启动
    if thread_count is None:
        try:
            t = int(input("\n并发数 (默认8): ").strip() or 8)
        except:
            t = 8
    else:
        t = int(thread_count)

    if total_count is None:
        try:
            total = int(input("注册数量 (默认100): ").strip() or 100)
        except:
            total = 100
    else:
        total = int(total_count)

    global target_count, max_attempts, output_file
    target_count = max(1, total)
    max_attempts = compute_effective_max_attempts(target_count, max_attempts_arg)
    reset_runtime_state()

    from datetime import datetime
    os.makedirs("keys", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"keys/grok_{timestamp}_{target_count}.txt"

    print(f"[*] 启动 {t} 个线程，目标 {target_count} 个")
    print(f"[*] 最大尝试上限: {max_attempts}")
    if max_attempts_arg is None:
        print(
            f"[*] 未指定 --max-attempts，自动使用 {max_attempts}。"
            f"如网络不稳定可手动调整（例如 --max-attempts {target_count * 4}）。"
        )
    print(f"[*] 输出: {output_file}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=t) as executor:
        futures = [executor.submit(register_single_thread) for _ in range(t)]
        concurrent.futures.wait(futures)
    print(f"[*] 运行结束: 成功 {success_count}/{target_count}，尝试 {attempt_count}/{max_attempts}")
    if attempt_limit_reached.is_set() and success_count < target_count:
        print("[!] 已达到最大尝试上限，提前停止。请检查代理/网络后重试。 [ATTEMPT_LIMIT_REACHED]")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grok batch registration")
    parser.add_argument("--threads", type=int, default=None, help="并发数")
    parser.add_argument("--count", type=int, default=None, help="注册数量")
    parser.add_argument("--max-attempts", type=int, default=None, help="最大尝试次数（默认按 count 自动计算）")
    args = parser.parse_args()
    main(thread_count=args.threads, total_count=args.count, max_attempts_arg=args.max_attempts)
