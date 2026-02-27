import unittest
from unittest.mock import Mock, patch

import grok


class EmailCodeFlowTests(unittest.TestCase):
    def test_continue_polling_even_when_send_request_not_confirmed(self):
        email_service = Mock()
        email_service.fetch_verification_code.side_effect = [None, "123456"]

        with patch("grok.send_email_code_grpc", side_effect=[False, True]) as send_mock:
            code = grok.request_and_wait_for_email_code(
                session=Mock(),
                email_service=email_service,
                email="demo@example.com",
                max_request_rounds=3,
                poll_attempts_per_round=180,
            )

        self.assertEqual(code, "123456")
        self.assertEqual(send_mock.call_count, 2)
        self.assertEqual(email_service.fetch_verification_code.call_count, 2)
        email_service.fetch_verification_code.assert_any_call(
            "demo@example.com", max_attempts=180, exclude_codes=None
        )

    def test_return_none_after_three_rounds_without_code(self):
        email_service = Mock()
        email_service.fetch_verification_code.side_effect = [None, None, None]

        with patch("grok.send_email_code_grpc", return_value=False) as send_mock:
            code = grok.request_and_wait_for_email_code(
                session=Mock(),
                email_service=email_service,
                email="demo@example.com",
                max_request_rounds=3,
                poll_attempts_per_round=180,
            )

        self.assertIsNone(code)
        self.assertEqual(send_mock.call_count, 3)
        self.assertEqual(email_service.fetch_verification_code.call_count, 3)


if __name__ == "__main__":
    unittest.main()
