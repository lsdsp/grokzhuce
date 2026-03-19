import concurrent.futures
import os
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from curl_cffi import requests

from g import EmailService, NsfwSettingsService, TurnstileService, UserAgreementService
from grok_config import DEFAULT_SITE_URL, build_default_runtime_context, should_delete_email_after_registration
from grok_protocol import (
    MAX_EMAIL_CODE_CYCLES_PER_EMAIL,
    compact_text,
    generate_random_string,
    get_random_chrome_profile,
    mask_email,
    request_and_wait_for_email_code,
    scan_signup_bootstrap,
    verify_email_code_grpc,
)
from grok_protocol_signup import attempt_signup
from grok_runtime import AppConfig, ErrorType, JsonlLogger, LOGGER, RuntimeContext, StageResult, StopPolicy, StopReason


@dataclass
class ServiceBundle:
    email_service: EmailService
    turnstile_service: TurnstileService
    tos_service: UserAgreementService
    nsfw_service: NsfwSettingsService


class GrokRunner:
    def __init__(
        self,
        cfg: AppConfig,
        *,
        runtime: Optional[RuntimeContext] = None,
        site_url: str = DEFAULT_SITE_URL,
    ):
        self.cfg = cfg
        self.site_url = site_url
        self.runtime = runtime or build_default_runtime_context()
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
        fields = {key: value for key, value in fields.items() if value not in (None, "")}
        self.metrics.event(level, stage, message, **fields)
        getattr(LOGGER, level.lower() if hasattr(LOGGER, level.lower()) else "info")(message)

    def _fail(self, result: StageResult, thread_id: int, attempt_no: int, email: str = ""):
        self.error_counts[result.error_type.value] = self.error_counts.get(result.error_type.value, 0) + 1
        self._log(
            "warning" if result.retryable else "error",
            result.stage,
            f"{result.stage} failed",
            thread_id=thread_id,
            attempt_no=attempt_no,
            email=mask_email(email),
            error_type=result.error_type.value,
            details=compact_text(result.details),
        )

    def _stage_emit(self, stage: str, thread_id: int, attempt_no: int, email: str = ""):
        masked = mask_email(email)

        def emit(level: str, message: str):
            normalized_level = "warning" if level.lower() in {"warning", "warn"} else "info"
            self._log(
                normalized_level,
                stage,
                message,
                thread_id=thread_id,
                attempt_no=attempt_no,
                email=masked,
            )

        return emit

    def scan_bootstrap(self) -> StageResult:
        return scan_signup_bootstrap(self.runtime, self.cfg.proxies, site_url=self.site_url)

    def _create_services(self, thread_id: int) -> Optional[ServiceBundle]:
        try:
            return ServiceBundle(
                email_service=EmailService(),
                turnstile_service=TurnstileService(),
                tos_service=UserAgreementService(),
                nsfw_service=NsfwSettingsService(),
            )
        except Exception as exc:
            self._log(
                "error",
                "bootstrap_thread",
                f"[T{thread_id}] 服务初始化失败: {exc}",
                thread_id=thread_id,
                error_type=ErrorType.DEPENDENCY.value,
            )
            return None

    def _create_identity(self, services: ServiceBundle, thread_id: int, attempt_no: int) -> StageResult:
        try:
            _jwt, email = services.email_service.create_email()
        except Exception as exc:
            return StageResult(False, "create_identity", ErrorType.DEPENDENCY, True, str(exc))
        if not email:
            return StageResult(False, "create_identity", ErrorType.DEPENDENCY, True, "创建邮箱失败")
        return StageResult(True, "create_identity", data={"email": email, "password": generate_random_string()})

    def _request_code(self, session, services: ServiceBundle, email: str, thread_id: int, attempt_no: int, used_codes) -> StageResult:
        code = request_and_wait_for_email_code(
            session=session,
            email_service=services.email_service,
            email=email,
            excluded_codes=used_codes,
            display_email=mask_email(email),
            emit=self._stage_emit("request_code", thread_id, attempt_no, email),
            site_url=self.site_url,
        )
        if not code:
            return StageResult(False, "request_code", ErrorType.TIMEOUT, True, "未收到验证码")
        return StageResult(True, "request_code", data={"code": code})

    def _verify_code(self, session, email: str, code: str, thread_id: int, attempt_no: int) -> StageResult:
        ok = verify_email_code_grpc(
            session,
            email,
            code,
            site_url=self.site_url,
            display_email=mask_email(email),
            emit=self._stage_emit("verify_code", thread_id, attempt_no, email),
        )
        if not ok:
            return StageResult(False, "verify_code", ErrorType.SIGNUP, True, "验证码校验失败")
        return StageResult(True, "verify_code", data={"code": code})

    def _attempt_signup(self, session, services: ServiceBundle, email: str, password: str, code: str, impersonate: str, user_agent: str) -> StageResult:
        return attempt_signup(
            session=session,
            turnstile_service=services.turnstile_service,
            runtime=self.runtime,
            site_url=self.site_url,
            email=email,
            password=password,
            code=code,
            impersonate=impersonate,
            user_agent=user_agent,
            post_lock=self.post_lock,
        )

    def _run_post_signup_actions(self, services: ServiceBundle, signup_result: StageResult) -> StageResult:
        data = signup_result.data
        sso = data["sso"]
        sso_rw = data["sso_rw"] or ""
        impersonate = data["impersonate"]
        user_agent = data["user_agent"]
        tos = services.tos_service.accept_tos_version(
            sso=sso,
            sso_rw=sso_rw,
            impersonate=impersonate,
            user_agent=user_agent,
        )
        if not tos.get("ok") or not tos.get("hex_reply"):
            return StageResult(
                False,
                "post_signup_actions",
                ErrorType.SIGNUP,
                False,
                (
                    "TOS 失败: "
                    f"error={tos.get('error')}, "
                    f"http={tos.get('status_code')}, "
                    f"grpc={tos.get('grpc_status')}, "
                    f"sso_rw={'yes' if bool(sso_rw) else 'no'}"
                ),
            )

        nsfw_tag = "OFF"
        nsfw_detail = ""
        if self.cfg.enable_nsfw:
            birth = services.nsfw_service.set_birth_date(
                sso=sso,
                sso_rw=sso_rw,
                impersonate=impersonate,
                user_agent=user_agent,
            )
            if not birth.get("ok"):
                return StageResult(
                    False,
                    "post_signup_actions",
                    ErrorType.SIGNUP,
                    False,
                    (
                        "SET_BIRTH 失败: "
                        f"error={birth.get('error')}, "
                        f"http={birth.get('status_code')}, "
                        f"endpoint={birth.get('endpoint')}"
                    ),
                )
            nsfw = services.nsfw_service.enable_nsfw(
                sso=sso,
                sso_rw=sso_rw,
                impersonate=impersonate,
                user_agent=user_agent,
            )
            if not nsfw.get("ok") or not nsfw.get("hex_reply"):
                return StageResult(
                    False,
                    "post_signup_actions",
                    ErrorType.SIGNUP,
                    False,
                    (
                        "NSFW 失败: "
                        f"error={nsfw.get('error')}, "
                        f"http={nsfw.get('status_code')}, "
                        f"grpc={nsfw.get('grpc_status')}, "
                        f"endpoint={nsfw.get('endpoint')}"
                    ),
                )
            unhinged = services.nsfw_service.enable_unhinged(
                sso=sso,
                sso_rw=sso_rw,
                impersonate=impersonate,
                user_agent=user_agent,
            )
            detail_parts = []
            if unhinged.get("grpc_status") not in (None, ""):
                detail_parts.append(f"grpc={unhinged.get('grpc_status')}")
            if unhinged.get("endpoint"):
                detail_parts.append(f"endpoint={unhinged.get('endpoint')}")
            if unhinged.get("feature_key"):
                detail_parts.append(f"feature={unhinged.get('feature_key')}")
            if unhinged.get("error"):
                detail_parts.append(f"error={unhinged.get('error')}")
            attempt_summaries = []
            for attempt in unhinged.get("attempts", []):
                feature = attempt.get("feature_key") or "unknown"
                grpc_status = attempt.get("grpc_status")
                status_code = attempt.get("status_code")
                if grpc_status not in (None, ""):
                    suffix = f"grpc{grpc_status}"
                elif status_code not in (None, ""):
                    suffix = f"http{status_code}"
                else:
                    suffix = "unknown"
                attempt_summaries.append(f"{feature}@{suffix}")
            if attempt_summaries:
                detail_parts.append(f"tried={','.join(attempt_summaries)}")
            nsfw_detail = " | ".join(detail_parts)
            nsfw_tag = "OK"
            if not unhinged.get("supported", True):
                nsfw_tag = "SKIP"
            elif not unhinged.get("ok", False):
                nsfw_tag = "WARN"
        return StageResult(True, "post_signup_actions", data={"nsfw_tag": nsfw_tag, "nsfw_detail": nsfw_detail, "sso": sso})

    def _record_success(self, sso: str, email: str, thread_id: int, attempt_no: int, nsfw_tag: str, nsfw_detail: str = ""):
        with self.write_lock:
            with open(self.cfg.output_file, "a", encoding="utf-8") as handle:
                handle.write(sso + "\n")
            done = self.stop.mark_success()
            avg = (time.time() - self.start_ts) / max(1, done)
        detail_suffix = f" | {nsfw_detail}" if nsfw_detail else ""
        self._log(
            "info",
            "record_success",
            f"[T{thread_id}] 注册成功: {done}/{self.stop.target_count} | {mask_email(email)} | 平均: {avg:.1f}s | NSFW: {nsfw_tag}{detail_suffix}",
            thread_id=thread_id,
            attempt_no=attempt_no,
            email=mask_email(email),
        )

    def _complete_registration_attempt(self, session, services: ServiceBundle, email: str, password: str, impersonate: str, user_agent: str, thread_id: int, attempt_no: int) -> bool:
        used_codes = set()
        for _ in range(MAX_EMAIL_CODE_CYCLES_PER_EMAIL):
            request_result = self._request_code(session, services, email, thread_id, attempt_no, used_codes)
            if not request_result.ok:
                self._fail(request_result, thread_id, attempt_no, email)
                break
            code = request_result.data["code"]

            verify_result = self._verify_code(session, email, code, thread_id, attempt_no)
            if not verify_result.ok:
                used_codes.add(code)
                self._fail(verify_result, thread_id, attempt_no, email)
                continue

            signup_result = self._attempt_signup(session, services, email, password, code, impersonate, user_agent)
            if not signup_result.ok and signup_result.data.get("code_invalid"):
                used_codes.add(code)
                self._log(
                    "warning",
                    "signup",
                    f"[T{thread_id}] 注册阶段返回验证码失效，准备重新发码",
                    thread_id=thread_id,
                    attempt_no=attempt_no,
                    email=mask_email(email),
                    error_type=ErrorType.SIGNUP.value,
                )
                continue
            if not signup_result.ok:
                self._fail(signup_result, thread_id, attempt_no, email)
                break

            post_result = self._run_post_signup_actions(services, signup_result)
            if not post_result.ok:
                self._fail(post_result, thread_id, attempt_no, email)
                break

            self._record_success(
                post_result.data["sso"],
                email,
                thread_id,
                attempt_no,
                post_result.data["nsfw_tag"],
                post_result.data.get("nsfw_detail", ""),
            )
            return True
        return False

    def worker(self, thread_id: int):
        time.sleep(random.uniform(0, 5))
        services = self._create_services(thread_id)
        if not services:
            return

        while not self.stop.should_stop():
            claim = self.stop.claim_attempt_slot()
            if not claim.allowed:
                break
            attempt_no = claim.slot_no
            if attempt_no <= 3 or attempt_no % 20 == 0:
                self._log(
                    "info",
                    "attempt",
                    f"[T{thread_id}] 全局尝试进度: {attempt_no}/{self.stop.max_attempts}",
                    attempt_no=attempt_no,
                    thread_id=thread_id,
                )

            current_email = ""
            success = False
            try:
                impersonate, user_agent = get_random_chrome_profile()
                with requests.Session(impersonate=impersonate, proxies=self.cfg.proxies or None) as session:
                    try:
                        session.get(self.site_url, timeout=10)
                    except Exception:
                        pass
                    identity = self._create_identity(services, thread_id, attempt_no)
                    if not identity.ok:
                        self._fail(identity, thread_id, attempt_no)
                        time.sleep(5)
                        continue
                    current_email = identity.data["email"]
                    success = self._complete_registration_attempt(
                        session,
                        services,
                        current_email,
                        identity.data["password"],
                        impersonate,
                        user_agent,
                        thread_id,
                        attempt_no,
                    )
            except Exception as exc:
                self._log(
                    "error",
                    "worker_exception",
                    f"[T{thread_id}] 线程异常: {compact_text(exc)}",
                    thread_id=thread_id,
                    attempt_no=attempt_no,
                    error_type=ErrorType.UNKNOWN.value,
                )
                time.sleep(5)
            finally:
                if current_email:
                    if should_delete_email_after_registration(success, self.cfg.keep_success_email):
                        try:
                            services.email_service.delete_email(current_email)
                        except Exception:
                            pass
                    else:
                        self._log(
                            "info",
                            "cleanup",
                            f"[T{thread_id}] 保留成功邮箱: {mask_email(current_email)}",
                            thread_id=thread_id,
                            attempt_no=attempt_no,
                            email=mask_email(current_email),
                        )
            if not success:
                time.sleep(5)

    def run(self) -> int:
        self._log("info", "startup", "正在初始化...", metrics_path=self.cfg.metrics_path)
        self._log("info", "startup", f"当前代理: {self.cfg.proxies.get('https') if self.cfg.proxies else '直连'}")
        self._log("info", "startup", f"成功后保留邮箱: {'ON' if self.cfg.keep_success_email else 'OFF'}")
        self._log("info", "startup", f"NSFW 开关: {'ON' if self.cfg.enable_nsfw else 'OFF'}")
        boot = self.scan_bootstrap()
        if not boot.ok:
            self._fail(boot, thread_id=0, attempt_no=0)
            return 1
        self._log("info", "scan_bootstrap", f"Action ID: {self.runtime.action_id}", latency_ms=boot.latency_ms)
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.cfg.thread_count) as executor:
            futures = [executor.submit(self.worker, index + 1) for index in range(self.cfg.thread_count)]
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    self._log("error", "executor", f"worker future 异常: {exc}", error_type=ErrorType.UNKNOWN.value)
        self._log(
            "info",
            "summary",
            f"运行结束: success={self.stop.success_count}/{self.stop.target_count}, attempts={self.stop.attempt_count}/{self.stop.max_attempts}, stop_reason={self.stop.stop_reason.value if self.stop.stop_reason else 'n/a'}",
        )
        for key, value in sorted(self.error_counts.items(), key=lambda item: item[1], reverse=True):
            self._log("info", "summary", f"failure_bucket {key}={value}")
        if self.stop.stop_reason == StopReason.ATTEMPT_LIMIT and self.stop.success_count < self.stop.target_count:
            self._log("warning", "summary", "已达到最大尝试上限，提前停止。 [ATTEMPT_LIMIT_REACHED]", error_type=ErrorType.POLICY.value)
        return 0 if self.stop.success_count >= self.stop.target_count else 1
