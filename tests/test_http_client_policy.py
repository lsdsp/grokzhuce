import unittest
from unittest.mock import patch

from g.http_client_policy import (
    build_impersonated_request_kwargs,
    build_plain_request_kwargs,
    create_local_session,
    should_verify_ssl,
)


class HttpClientPolicyTests(unittest.TestCase):
    def test_should_verify_ssl_defaults_to_false_when_proxy_exists(self):
        self.assertFalse(should_verify_ssl(None, "http://127.0.0.1:10808"))

    def test_should_verify_ssl_honors_explicit_true(self):
        self.assertTrue(should_verify_ssl("true", "http://127.0.0.1:10808"))

    def test_build_plain_request_kwargs_includes_timeout_proxies_and_verify(self):
        with patch.dict(
            "os.environ",
            {"MOEMAIL_PROXY_URL": "http://127.0.0.1:10808", "MOEMAIL_VERIFY_SSL": ""},
            clear=True,
        ):
            kwargs = build_plain_request_kwargs(
                preferred_proxy_keys=("MOEMAIL_PROXY_URL", "GROK_PROXY_URL"),
                verify_ssl_env_key="MOEMAIL_VERIFY_SSL",
                timeout=12,
            )

        self.assertEqual(kwargs["timeout"], 12)
        self.assertFalse(kwargs["verify"])
        self.assertEqual(
            kwargs["proxies"],
            {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"},
        )

    def test_build_impersonated_request_kwargs_includes_proxy_and_impersonate(self):
        with patch.dict(
            "os.environ",
            {"GROK_PROXY_URL": "http://127.0.0.1:10808"},
            clear=True,
        ):
            kwargs = build_impersonated_request_kwargs(
                preferred_proxy_keys=("GROK_PROXY_URL",),
                impersonate="chrome120",
                timeout=20,
            )

        self.assertEqual(kwargs["timeout"], 20)
        self.assertEqual(kwargs["impersonate"], "chrome120")
        self.assertEqual(
            kwargs["proxies"],
            {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"},
        )

    def test_create_local_session_disables_trust_env(self):
        class _Session:
            def __init__(self):
                self.trust_env = True

        session = create_local_session(_Session)

        self.assertFalse(session.trust_env)


if __name__ == "__main__":
    unittest.main()
