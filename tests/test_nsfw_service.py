import unittest
from unittest.mock import Mock, patch

from g.nsfw_service import NsfwSettingsService


class NsfwServiceTests(unittest.TestCase):
    def test_enable_nsfw_prefers_grok_domain_and_grpc_headers(self):
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
            "https://grok.com/auth_mgmt.AuthManagement/UpdateUserFeatureControls",
        )
        self.assertEqual(kwargs["headers"]["origin"], "https://grok.com")
        self.assertEqual(kwargs["headers"]["x-user-agent"], "connect-es/2.1.1")
        self.assertEqual(kwargs["headers"]["x-grpc-web"], "1")
        self.assertIn("sso=sso-token", kwargs["headers"]["cookie"])
        self.assertIn("sso-rw=sso-token", kwargs["headers"]["cookie"])
        self.assertEqual(
            result["endpoint"],
            "https://grok.com/auth_mgmt.AuthManagement/UpdateUserFeatureControls",
        )

    def test_enable_unhinged_prefers_grok_domain_and_cookie_dict(self):
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
            "https://grok.com/auth_mgmt.AuthManagement/UpdateUserFeatureControls",
        )
        kwargs = post_mock.call_args.kwargs
        self.assertEqual(kwargs["headers"]["origin"], "https://grok.com")
        self.assertIn("sso=sso-token", kwargs["headers"]["cookie"])
        self.assertIn("sso-rw=sso-token", kwargs["headers"]["cookie"])
        self.assertTrue(result["supported"])
        self.assertEqual(
            result["endpoint"],
            "https://grok.com/auth_mgmt.AuthManagement/UpdateUserFeatureControls",
        )

    def test_enable_nsfw_fallbacks_to_accounts_domain_when_grok_is_forbidden(self):
        service = NsfwSettingsService()

        forbidden = Mock()
        forbidden.status_code = 403
        forbidden.content = b""
        forbidden.headers = {"grpc-status": "7"}

        ok_resp = Mock()
        ok_resp.status_code = 200
        ok_resp.content = b"\x00"
        ok_resp.headers = {"grpc-status": "0"}

        with patch("g.nsfw_service.requests.post", side_effect=[forbidden, ok_resp]) as post_mock:
            result = service.enable_nsfw(
                sso="sso-token",
                sso_rw="sso-rw-token",
                impersonate="chrome120",
                user_agent="ua-test",
            )

        self.assertEqual(post_mock.call_count, 2)
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["endpoint"],
            "https://accounts.x.ai/auth_mgmt.AuthManagement/UpdateUserFeatureControls",
        )

    def test_set_birth_date_uses_grok_rest_endpoint(self):
        service = NsfwSettingsService()

        resp = Mock()
        resp.status_code = 200

        with patch("g.nsfw_service.requests.post", return_value=resp) as post_mock:
            result = service.set_birth_date(
                sso="sso-token",
                sso_rw="sso-rw-token",
                impersonate="chrome120",
                user_agent="ua-test",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            post_mock.call_args.args[0],
            "https://grok.com/rest/auth/set-birth-date",
        )
        kwargs = post_mock.call_args.kwargs
        self.assertEqual(kwargs["headers"]["origin"], "https://grok.com")
        self.assertIn("sso=sso-token", kwargs["headers"]["cookie"])
        self.assertIn("sso-rw=sso-token", kwargs["headers"]["cookie"])
        self.assertIn("birthDate", kwargs["json"])
        self.assertEqual(result["endpoint"], "https://grok.com/rest/auth/set-birth-date")

    def test_set_birth_date_fallbacks_to_accounts_domain_when_grok_is_forbidden(self):
        service = NsfwSettingsService()

        forbidden = Mock()
        forbidden.status_code = 403

        ok_resp = Mock()
        ok_resp.status_code = 200

        with patch("g.nsfw_service.requests.post", side_effect=[forbidden, ok_resp]) as post_mock:
            result = service.set_birth_date(
                sso="sso-token",
                sso_rw="sso-rw-token",
                impersonate="chrome120",
                user_agent="ua-test",
            )

        self.assertEqual(post_mock.call_count, 2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["endpoint"], "https://accounts.x.ai/rest/auth/set-birth-date")

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
