import unittest
from unittest.mock import Mock

import grok


class VerifyEmailCodeTests(unittest.TestCase):
    def test_verify_fails_when_grpc_status_is_not_zero(self):
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.headers = {"grpc-status": "3"}
        response.text = ""
        session.post.return_value = response

        ok = grok.verify_email_code_grpc(session, "demo@example.com", "123456")

        self.assertFalse(ok)

    def test_verify_fails_when_body_contains_invalid_code_error(self):
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.headers = {"grpc-status": "0"}
        response.text = (
            '1:{"error":"[invalid_argument] Email validation code is invalid '
            '[WKE=email:invalid-validation-code]"}'
        )
        session.post.return_value = response

        ok = grok.verify_email_code_grpc(session, "demo@example.com", "123456")

        self.assertFalse(ok)

    def test_verify_passes_when_http_and_grpc_are_ok_and_no_error_body(self):
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.headers = {"grpc-status": "0"}
        response.text = ""
        session.post.return_value = response

        ok = grok.verify_email_code_grpc(session, "demo@example.com", "123456")

        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
