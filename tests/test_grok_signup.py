import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from grok_protocol_signup import attempt_signup, extract_set_cookie_redirect_url


class SignupAdapterTests(unittest.TestCase):
    def test_extract_set_cookie_redirect_url_trims_stream_frame_suffix(self):
        response_text = '0:["$","$L1",null,"https://accounts.x.ai/set-cookie?q=abc1231:"]'

        redirect_url = extract_set_cookie_redirect_url(response_text)

        self.assertEqual(
            redirect_url,
            "https://accounts.x.ai/set-cookie?q=abc123",
        )

    def test_attempt_signup_returns_code_invalid_when_body_contains_invalid_code_marker(self):
        session = Mock()
        session.cookies.get.return_value = ""
        response = Mock()
        response.status_code = 200
        response.text = '1:{"error":"[invalid_argument] Email validation code is invalid"}'
        session.post.return_value = response

        turnstile_service = Mock()
        turnstile_service.create_task.return_value = "task-1"
        turnstile_service.get_response.return_value = "token-abc"

        result = attempt_signup(
            session=session,
            turnstile_service=turnstile_service,
            runtime=SimpleNamespace(site_key="site-key", state_tree="tree", action_id="action-id"),
            site_url="https://accounts.x.ai",
            email="demo@example.com",
            password="pass123",
            code="123456",
            impersonate="chrome120",
            user_agent="ua-test",
        )

        self.assertFalse(result.ok)
        self.assertTrue(result.data["code_invalid"])

    def test_attempt_signup_returns_sso_tokens_after_set_cookie_followup(self):
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.text = '0:["$","$L1",null,"https://accounts.x.ai/set-cookie?q=abc1231:"]'
        session.post.return_value = response
        session.get.return_value = Mock(status_code=200)
        session.cookies.get.side_effect = lambda name, default="": {
            "__cf_bm": "cf-cookie",
            "sso": "sso-token",
            "sso-rw": "sso-rw-token",
        }.get(name, default)

        turnstile_service = Mock()
        turnstile_service.create_task.return_value = "task-2"
        turnstile_service.get_response.return_value = "token-xyz"

        with patch("grok_protocol_signup.generate_random_name", side_effect=["Alice", "Smith"]):
            result = attempt_signup(
                session=session,
                turnstile_service=turnstile_service,
                runtime=SimpleNamespace(site_key="site-key", state_tree="tree", action_id="action-id"),
                site_url="https://accounts.x.ai",
                email="demo@example.com",
                password="pass123",
                code="123456",
                impersonate="chrome120",
                user_agent="ua-test",
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.data["sso"], "sso-token")
        self.assertEqual(result.data["sso_rw"], "sso-rw-token")
        self.assertEqual(result.data["impersonate"], "chrome120")
        self.assertEqual(result.data["user_agent"], "ua-test")
        session.get.assert_called_once_with(
            "https://accounts.x.ai/set-cookie?q=abc123",
            allow_redirects=True,
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
