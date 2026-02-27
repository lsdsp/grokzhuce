import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from g.turnstile_service import TurnstileService


class TurnstileServiceLocalSolverTests(unittest.TestCase):
    def test_create_task_urlencodes_siteurl_and_sitekey(self):
        with patch.dict("os.environ", {"YESCAPTCHA_KEY": ""}, clear=False):
            service = TurnstileService(solver_url="http://127.0.0.1:5072")
        self.assertFalse(service.local_session.trust_env)

        response = Mock()
        response.json.return_value = {"taskId": "task-123"}
        response.raise_for_status.return_value = None

        with patch.object(service.local_session, "get", return_value=response) as get_mock:
            task_id = service.create_task(
                "https://example.com/path?a=1&b=2",
                "site key+/=",
            )

        self.assertEqual(task_id, "task-123")
        called_url = get_mock.call_args.args[0]
        parsed = urlparse(called_url)
        query = parse_qs(parsed.query)
        self.assertEqual(query["url"], ["https://example.com/path?a=1&b=2"])
        self.assertEqual(query["sitekey"], ["site key+/="])

    def test_get_response_retries_processing_then_returns_ready_token(self):
        with patch.dict("os.environ", {"YESCAPTCHA_KEY": ""}, clear=False):
            service = TurnstileService(solver_url="http://127.0.0.1:5072")

        processing = Mock()
        processing.raise_for_status.return_value = None
        processing.json.return_value = {"status": "processing"}

        ready = Mock()
        ready.raise_for_status.return_value = None
        ready.json.return_value = {"status": "ready", "solution": {"token": "token-xyz"}}

        with patch("time.sleep", return_value=None):
            with patch.object(service.local_session, "get", side_effect=[processing, ready]) as get_mock:
                token = service.get_response("task-123", max_retries=3, initial_delay=0, retry_delay=0)

        self.assertEqual(token, "token-xyz")
        self.assertEqual(get_mock.call_count, 2)

    def test_get_response_returns_none_immediately_on_unsolvable(self):
        with patch.dict("os.environ", {"YESCAPTCHA_KEY": ""}, clear=False):
            service = TurnstileService(solver_url="http://127.0.0.1:5072")

        unsolvable = Mock()
        unsolvable.raise_for_status.return_value = None
        unsolvable.json.return_value = {
            "errorId": 1,
            "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
            "errorDescription": "Workers could not solve the Captcha",
        }

        with patch("time.sleep", return_value=None):
            with patch.object(service.local_session, "get", return_value=unsolvable) as get_mock:
                token = service.get_response("task-123", max_retries=5, initial_delay=0, retry_delay=0)

        self.assertIsNone(token)
        self.assertEqual(get_mock.call_count, 1)


class TurnstileServiceYesCaptchaTests(unittest.TestCase):
    def test_create_task_with_yescaptcha_uses_timeout(self):
        with patch.dict("os.environ", {"YESCAPTCHA_KEY": "yes-test-key"}, clear=False):
            service = TurnstileService()

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"errorId": 0, "taskId": "task-yes-1"}

        with patch("g.turnstile_service.requests.post", return_value=response) as post_mock:
            task_id = service.create_task("https://example.com", "sitekey")

        self.assertEqual(task_id, "task-yes-1")
        self.assertEqual(post_mock.call_args.kwargs["timeout"], service.YESCAPTCHA_TIMEOUT)

    def test_get_response_with_yescaptcha_uses_timeout(self):
        with patch.dict("os.environ", {"YESCAPTCHA_KEY": "yes-test-key"}, clear=False):
            service = TurnstileService()

        ready = Mock()
        ready.raise_for_status.return_value = None
        ready.json.return_value = {"errorId": 0, "status": "ready", "solution": {"token": "token-yes"}}

        with patch("time.sleep", return_value=None):
            with patch("g.turnstile_service.requests.post", return_value=ready) as post_mock:
                token = service.get_response("task-yes-1", max_retries=1, initial_delay=0, retry_delay=0)

        self.assertEqual(token, "token-yes")
        self.assertEqual(post_mock.call_args.kwargs["timeout"], service.YESCAPTCHA_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
