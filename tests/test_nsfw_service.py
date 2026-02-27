import unittest
from unittest.mock import Mock, patch

from g.nsfw_service import NsfwSettingsService


class NsfwServiceTests(unittest.TestCase):
    def test_enable_nsfw_uses_accounts_domain_and_grpc_headers(self):
        service = NsfwSettingsService()

        resp = Mock()
        resp.status_code = 200
        resp.content = b"\x00"
        resp.headers = {"grpc-status": "0"}

        with patch("g.nsfw_service.requests.post", return_value=resp) as post_mock:
            result = service.enable_nsfw(
                sso="sso-token",
                sso_rw="sso-rw-token",
                impersonate="chrome120",
                user_agent="ua-test",
            )

        self.assertTrue(result["ok"])
        kwargs = post_mock.call_args.kwargs
        self.assertEqual(
            post_mock.call_args.args[0],
            "https://accounts.x.ai/auth_mgmt.AuthManagement/UpdateUserFeatureControls",
        )
        self.assertEqual(kwargs["headers"]["origin"], "https://accounts.x.ai")
        self.assertEqual(kwargs["headers"]["x-user-agent"], "connect-es/2.1.1")
        self.assertEqual(kwargs["headers"]["x-grpc-web"], "1")
        self.assertEqual(kwargs["cookies"]["sso"], "sso-token")
        self.assertEqual(kwargs["cookies"]["sso-rw"], "sso-rw-token")

    def test_enable_unhinged_uses_accounts_domain_and_cookie_dict(self):
        service = NsfwSettingsService()

        resp = Mock()
        resp.status_code = 200
        resp.headers = {"grpc-status": "0"}
        resp.content = b"\x00"

        with patch("g.nsfw_service.requests.post", return_value=resp) as post_mock:
            result = service.enable_unhinged(
                sso="sso-token",
                sso_rw="sso-rw-token",
                impersonate="chrome120",
                user_agent="ua-test",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            post_mock.call_args.args[0],
            "https://accounts.x.ai/auth_mgmt.AuthManagement/UpdateUserFeatureControls",
        )
        kwargs = post_mock.call_args.kwargs
        self.assertEqual(kwargs["headers"]["origin"], "https://accounts.x.ai")
        self.assertEqual(kwargs["cookies"]["sso"], "sso-token")
        self.assertEqual(kwargs["cookies"]["sso-rw"], "sso-rw-token")
        self.assertTrue(result["supported"])

    def test_enable_unhinged_gracefully_skips_when_feature_is_unsupported(self):
        service = NsfwSettingsService()

        unsupported = Mock()
        unsupported.status_code = 200
        unsupported.headers = {"grpc-status": "13"}
        unsupported.content = b""

        with patch("g.nsfw_service.requests.post", return_value=unsupported):
            result = service.enable_unhinged(
                sso="sso-token",
                sso_rw="sso-rw-token",
                impersonate="chrome120",
                user_agent="ua-test",
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["supported"])
        self.assertEqual(result["grpc_status"], "13")


if __name__ == "__main__":
    unittest.main()
