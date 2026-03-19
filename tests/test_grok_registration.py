import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from grok_registration import GrokRunner
from grok_runtime import AppConfig, AttemptClaim, ErrorType, RuntimeContext, StageResult, StopReason


class _CompletedFuture:
    def __init__(self, value=None):
        self._value = value

    def result(self):
        return self._value


class _InlineExecutor:
    def __init__(self, *args, **kwargs):
        self.futures = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, fn, *args, **kwargs):
        future = _CompletedFuture(fn(*args, **kwargs))
        self.futures.append(future)
        return future


class GrokRegistrationTests(unittest.TestCase):
    def _build_runner(self, *, target_count=1, max_attempts=2, enable_nsfw=False):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        cfg = AppConfig(
            thread_count=1,
            target_count=target_count,
            max_attempts=max_attempts,
            keep_success_email=False,
            enable_nsfw=enable_nsfw,
            output_file=str(root / "keys.txt"),
            proxies={},
            metrics_path=str(root / "metrics.jsonl"),
        )
        runtime = RuntimeContext(site_key="site-key", action_id="action-id", state_tree="state-tree")
        return GrokRunner(cfg, runtime=runtime, site_url="https://accounts.x.ai")

    def test_worker_startup_path_executes_without_crashing(self):
        runner = self._build_runner()
        services = SimpleNamespace(email_service=SimpleNamespace(delete_email=MagicMock()))

        with patch("grok_registration.random.uniform", return_value=0), patch("grok_registration.time.sleep", return_value=None), patch.object(
            runner, "_create_services", return_value=services
        ) as create_services_mock, patch.object(
            runner.stop, "should_stop", side_effect=[False, True]
        ), patch.object(
            runner.stop, "claim_attempt_slot", return_value=AttemptClaim(True, 1, None)
        ), patch.object(
            runner, "_create_identity", return_value=StageResult(False, "create_identity", ErrorType.DEPENDENCY, True, "boom")
        ) as create_identity_mock:
            runner.worker(thread_id=1)

        create_services_mock.assert_called_once_with(1)
        create_identity_mock.assert_called_once_with(services, 1, 1)

    def test_run_returns_zero_when_target_reached(self):
        runner = self._build_runner(target_count=1, max_attempts=3)

        def fake_worker(_thread_id):
            runner.stop.mark_success()

        with patch.object(runner, "scan_bootstrap", return_value=StageResult(True, "scan_bootstrap")), patch(
            "grok_registration.concurrent.futures.ThreadPoolExecutor", _InlineExecutor
        ), patch(
            "grok_registration.concurrent.futures.as_completed", side_effect=lambda futures: futures
        ), patch.object(
            runner, "worker", side_effect=fake_worker
        ):
            code = runner.run()

        self.assertEqual(code, 0)
        self.assertEqual(runner.stop.stop_reason, StopReason.TARGET_REACHED)

    def test_run_returns_one_when_success_count_stays_below_target(self):
        runner = self._build_runner(target_count=2, max_attempts=2)

        def fake_worker(_thread_id):
            runner.stop.claim_attempt_slot()
            runner.stop.stop_reason = StopReason.ATTEMPT_LIMIT
            runner.stop.stop_event.set()

        with patch.object(runner, "scan_bootstrap", return_value=StageResult(True, "scan_bootstrap")), patch(
            "grok_registration.concurrent.futures.ThreadPoolExecutor", _InlineExecutor
        ), patch(
            "grok_registration.concurrent.futures.as_completed", side_effect=lambda futures: futures
        ), patch.object(
            runner, "worker", side_effect=fake_worker
        ):
            code = runner.run()

        self.assertEqual(code, 1)
        self.assertEqual(runner.stop.success_count, 0)
        self.assertEqual(runner.stop.stop_reason, StopReason.ATTEMPT_LIMIT)

    def test_run_returns_one_when_bootstrap_fails(self):
        runner = self._build_runner()

        with patch.object(
            runner,
            "scan_bootstrap",
            return_value=StageResult(False, "scan_bootstrap", ErrorType.NETWORK, True, "offline"),
        ), patch("grok_registration.concurrent.futures.ThreadPoolExecutor") as executor_mock:
            code = runner.run()

        self.assertEqual(code, 1)
        executor_mock.assert_not_called()

    def test_run_post_signup_actions_returns_unhinged_skip_diagnostics(self):
        runner = self._build_runner(enable_nsfw=True)
        services = SimpleNamespace(
            tos_service=SimpleNamespace(accept_tos_version=lambda **kwargs: {"ok": True, "hex_reply": "01"}),
            nsfw_service=SimpleNamespace(
                set_birth_date=lambda **kwargs: {"ok": True},
                enable_nsfw=lambda **kwargs: {"ok": True, "hex_reply": "01"},
                enable_unhinged=lambda **kwargs: {
                    "ok": True,
                    "supported": False,
                    "grpc_status": "13",
                    "endpoint": "https://grok.com/auth_mgmt.AuthManagement/UpdateUserFeatureControls",
                    "attempts": [
                        {
                            "feature_key": "always_enable_unhinged_mode",
                            "grpc_status": "13",
                            "endpoint": "https://grok.com/auth_mgmt.AuthManagement/UpdateUserFeatureControls",
                        },
                        {
                            "feature_key": "always_use_unhinged_mode",
                            "grpc_status": "3",
                            "endpoint": "https://accounts.x.ai/auth_mgmt.AuthManagement/UpdateUserFeatureControls",
                        },
                    ],
                },
            ),
        )
        signup_result = StageResult(
            True,
            "signup",
            data={
                "sso": "sso-token",
                "sso_rw": "sso-rw-token",
                "impersonate": "chrome120",
                "user_agent": "ua-test",
            },
        )

        result = runner._run_post_signup_actions(services, signup_result)

        self.assertTrue(result.ok)
        self.assertEqual(result.data["nsfw_tag"], "SKIP")
        self.assertIn("grpc=13", result.data["nsfw_detail"])
        self.assertIn("tried=always_enable_unhinged_mode@grpc13,always_use_unhinged_mode@grpc3", result.data["nsfw_detail"])

    def test_record_success_appends_nsfw_detail_when_present(self):
        runner = self._build_runner()

        with patch.object(runner.stop, "mark_success", return_value=1), patch("grok_registration.time.time", return_value=100.0), patch.object(
            runner, "_log"
        ) as log_mock:
            runner._record_success(
                "sso-token",
                "demo@example.com",
                thread_id=1,
                attempt_no=2,
                nsfw_tag="SKIP",
                nsfw_detail="unhinged grpc=13 endpoint=https://grok.com/auth_mgmt.AuthManagement/UpdateUserFeatureControls",
            )

        message = log_mock.call_args.args[2]
        self.assertIn("NSFW: SKIP", message)
        self.assertIn("grpc=13", message)
        self.assertIn("endpoint=https://grok.com/auth_mgmt.AuthManagement/UpdateUserFeatureControls", message)


if __name__ == "__main__":
    unittest.main()
