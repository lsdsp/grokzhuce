import os, json, random, string, time, re, struct
import threading
import concurrent.futures
from urllib.parse import urljoin, urlparse
from curl_cffi import requests
from bs4 import BeautifulSoup

from g import EmailService, TurnstileService, UserAgreementService, NsfwSettingsService

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
PROXIES = {
    # "http": "http://127.0.0.1:10808",
    # "https": "http://127.0.0.1:10808"
}

# 动态获取的全局变量
config = {
    "site_key": "0x4AAAAAAAhr9JGVDZbrZOo0",
    "action_id": None,
    "state_tree": "%5B%22%22%2C%7B%22children%22%3A%5B%22(app)%22%2C%7B%22children%22%3A%5B%22(auth)%22%2C%7B%22children%22%3A%5B%22sign-up%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2Fsign-up%22%2C%22refresh%22%5D%7D%5D%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%2Ctrue%5D"
}

post_lock = threading.Lock()
file_lock = threading.Lock()
success_count = 0
start_time = time.time()
target_count = 100
stop_event = threading.Event()
output_file = None

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
        res = session.post(url, data=data, headers=headers, timeout=15)
        # print(f"[debug] {email} 请求结束，状态码: {res.status_code}")
        return res.status_code == 200
    except Exception as e:
        print(f"[-] {email} 发送验证码异常: {e}")
        return False

def verify_email_code_grpc(session, email, code):
    url = f"{site_url}/auth_mgmt.AuthManagement/VerifyEmailValidationCode"
    data = encode_grpc_message_verify(email, code)
    headers = {"content-type": "application/grpc-web+proto", "x-grpc-web": "1", "x-user-agent": "connect-es/2.1.1", "origin": site_url, "referer": f"{site_url}/sign-up?redirect=grok-com"}
    try:
        res = session.post(url, data=data, headers=headers, timeout=15)
        # print(f"[debug] {email} 验证响应状态: {res.status_code}, 内容长度: {len(res.content)}")
        return res.status_code == 200
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
    
    while True:
        try:
            if stop_event.is_set():
                return
            impersonate_fingerprint, account_user_agent = get_random_chrome_profile()
            with requests.Session(impersonate=impersonate_fingerprint, proxies=PROXIES) as session:
                # 预热连接
                try: session.get(site_url, timeout=10)
                except: pass

                password = generate_random_string()
                
                # print(f"[debug] 线程-{threading.get_ident()} 正在请求创建邮箱...")
                try:
                    jwt, email = email_service.create_email()
                except Exception as e:
                    print(f"[-] 邮箱服务抛出异常: {e}")
                    jwt, email = None, None

                if not email:
                    time.sleep(5); continue

                if stop_event.is_set():
                    if email:
                        email_service.delete_email(email)
                    return
                
                print(f"[*] 开始注册: {email}")

                # Step 1: 发送验证码
                if not send_email_code_grpc(session, email):
                    email_service.delete_email(email)
                    time.sleep(5); continue

                # Step 2: 获取验证码
                verify_code = email_service.fetch_verification_code(email)
                if not verify_code:
                    email_service.delete_email(email)
                    continue

                # Step 3: 验证验证码
                if not verify_email_code_grpc(session, email, verify_code):
                    email_service.delete_email(email)
                    continue
                
                # Step 4: 注册重试循环
                for attempt in range(3):
                    if stop_event.is_set():
                        email_service.delete_email(email)
                        return
                    task_id = turnstile_service.create_task(site_url, config["site_key"])
                    # 这里不再打印获取 Token 的过程，只在失败时报错
                    token = turnstile_service.get_response(task_id)
                    
                    if not token or token == "CAPTCHA_FAIL":
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
                        res = session.post(f"{site_url}/sign-up", json=payload, headers=headers)
                    
                    if res.status_code == 200:
                        match = re.search(r'(https://[^" \s]+set-cookie\?q=[^:" \s]+)1:', res.text)
                        if not match:
                            email_service.delete_email(email)
                            break
                        if match:
                            verify_url = match.group(1)
                            session.get(verify_url, allow_redirects=True)
                            sso = session.cookies.get("sso")
                            sso_rw = session.cookies.get("sso-rw")
                            if not sso:
                                email_service.delete_email(email)
                                break

                            tos_result = user_agreement_service.accept_tos_version(
                                sso=sso,
                                sso_rw=sso_rw or "",
                                impersonate=impersonate_fingerprint,
                                user_agent=account_user_agent,
                            )
                            tos_hex = tos_result.get("hex_reply") or ""
                            if not tos_result.get("ok") or not tos_hex:
                                email_service.delete_email(email)
                                break

                            nsfw_result = nsfw_service.enable_nsfw(
                                sso=sso,
                                sso_rw=sso_rw or "",
                                impersonate=impersonate_fingerprint,
                                user_agent=account_user_agent,
                            )
                            nsfw_hex = nsfw_result.get("hex_reply") or ""
                            if not nsfw_result.get("ok") or not nsfw_hex:
                                email_service.delete_email(email)
                                break

                            with file_lock:
                                global success_count
                                if success_count >= target_count:
                                    if not stop_event.is_set():
                                        stop_event.set()
                                    email_service.delete_email(email)
                                    break
                                with open(output_file, "a") as f: f.write(sso + "\n")
                                success_count += 1
                                avg = (time.time() - start_time) / success_count
                                print(f"[+] {success_count}/{target_count} {email} | {avg:.1f}s/个")
                                email_service.delete_email(email)
                                if success_count >= target_count and not stop_event.is_set():
                                    stop_event.set()
                            break  # 跳出 for 循环，继续 while True 注册下一个

                    time.sleep(3)
                else:
                    # 如果重试 3 次都失败 (for 循环没有被 break)
                    email_service.delete_email(email)
                    time.sleep(5)

        except Exception as e:
            print(f"[-] 异常: {str(e)[:50]}")
            time.sleep(5)

def main():
    print("=" * 60 + "\nGrok 注册机\n" + "=" * 60)
    
    # 1. 扫描参数
    print("[*] 正在初始化...")
    start_url = f"{site_url}/sign-up"
    with requests.Session(impersonate=DEFAULT_IMPERSONATE) as s:
        try:
            html = s.get(start_url).text
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
                js_content = s.get(js_url).text
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
    try:
        t = int(input("\n并发数 (默认8): ").strip() or 8)
    except: t = 8

    try:
        total = int(input("注册数量 (默认100): ").strip() or 100)
    except: total = 100

    global target_count, output_file
    target_count = max(1, total)

    from datetime import datetime
    os.makedirs("keys", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"keys/grok_{timestamp}_{target_count}.txt"

    print(f"[*] 启动 {t} 个线程，目标 {target_count} 个")
    print(f"[*] 输出: {output_file}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=t) as executor:
        futures = [executor.submit(register_single_thread) for _ in range(t)]
        concurrent.futures.wait(futures)

    # 二次验证 NSFW
    if os.path.exists(output_file):
        print(f"\n[*] 开始二次验证 NSFW...")
        nsfw_service = NsfwSettingsService()
        with open(output_file, "r") as f:
            tokens = [line.strip() for line in f if line.strip()]
        ok_count = 0
        for sso in tokens:
            result = nsfw_service.enable_unhinged(sso)
            if result.get("ok"):
                ok_count += 1
        print(f"[*] 二次验证完成: {ok_count}/{len(tokens)}")

if __name__ == "__main__":
    main()