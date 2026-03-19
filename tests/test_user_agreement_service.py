import unittest
from unittest.mock import Mock, patch

from g.user_agreement_service import UserAgreementService


class UserAgreementServiceTests(unittest.TestCase):
    def test_accept_tos_version_uses_impersonated_request_policy(self):
        service = UserAgreementService(proxy_url="http://127.0.0.1:10808")

        response = Mock()
        response.status_code = 200
        response.content = b"\x00"
        response.headers = {"grpc-status": "0"}

        with patch("g.user_agreement_service.requests.post", return_value=response) as post_mock:
            result = service.accept_tos_version(
                sso="sso-token",
                sso_rw="sso-rw-token",
                impersonate="chrome120",
                user_agent="ua-test",
                timeout=18,
            )

        self.assertTrue(result["ok"])
        kwargs = post_mock.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 18)
        self.assertEqual(kwargs["impersonate"], "chrome120")
        self.assertEqual(
            kwargs["proxies"],
            {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"},
        )
        self.assertEqual(kwargs["cookies"]["sso"], "sso-token")
        self.assertEqual(kwargs["cookies"]["sso-rw"], "sso-rw-token")


if __name__ == "__main__":
    unittest.main()
