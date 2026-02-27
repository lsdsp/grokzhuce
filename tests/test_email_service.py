import unittest
from unittest.mock import patch

from g.email_service import EmailService


class EmailServiceParsingTests(unittest.TestCase):
    def test_extract_email_from_wrapped_list_payload(self):
        payload = {"data": [{"email": "demo@example.com"}]}
        self.assertEqual(EmailService._extract_email(payload), "demo@example.com")

    def test_extract_email_items_from_single_dict_data(self):
        payload = {"data": {"subject": "Your code", "text": "123456"}}
        self.assertEqual(EmailService._extract_email_items(payload), [{"subject": "Your code", "text": "123456"}])

    def test_extract_email_items_from_plain_message_dict(self):
        payload = {"subject": "Your code", "text": "123456"}
        self.assertEqual(EmailService._extract_email_items(payload), [payload])

    def test_extract_verification_code_prefers_context_pattern(self):
        payload = {"html": "<div>您的验证码是：987654，请勿泄露</div>"}
        self.assertEqual(EmailService._extract_verification_code(payload), "987654")

    def test_extract_verification_code_subject_alnum(self):
        payload = {"subject": "8AK-4IJ xAI confirmation code"}
        self.assertEqual(EmailService._extract_verification_code(payload), "8AK4IJ")

    def test_sanitize_verification_code(self):
        self.assertEqual(EmailService._sanitize_verification_code("12-34 56"), "123456")

    def test_extract_verification_code_rejects_long_alpha_phrase(self):
        payload = {"text": "Your verification code will expire before best effort delivery"}
        self.assertIsNone(EmailService._extract_verification_code(payload))


class EmailServiceOpenApiFlowTests(unittest.TestCase):
    @staticmethod
    def _fake_response(status_code, payload):
        class _Resp:
            def __init__(self, code, data):
                self.status_code = code
                self._data = data
                self.text = "" if data is None else str(data)

            def json(self):
                if self._data is None:
                    raise ValueError("no json")
                return self._data

        return _Resp(status_code, payload)

    def _new_service(self):
        with patch.dict(
            "os.environ",
            {
                "MOEMAIL_API_KEY": "test-key",
                "MOEMAIL_API_URL": "https://api.moemail.app",
                "MOEMAIL_VERIFY_SSL": "true",
            },
            clear=False,
        ):
            return EmailService()

    def test_verify_ssl_empty_string_treated_as_unset(self):
        with patch.dict(
            "os.environ",
            {
                "MOEMAIL_API_KEY": "test-key",
                "MOEMAIL_API_URL": "https://api.moemail.app",
                "MOEMAIL_PROXY_URL": "http://127.0.0.1:10808",
                "MOEMAIL_VERIFY_SSL": "",
            },
            clear=False,
        ):
            service = EmailService()

        self.assertFalse(service.request_kwargs.get("verify"))

    def test_verify_ssl_false_string_disables_cert_validation(self):
        with patch.dict(
            "os.environ",
            {
                "MOEMAIL_API_KEY": "test-key",
                "MOEMAIL_API_URL": "https://api.moemail.app",
                "MOEMAIL_VERIFY_SSL": "false",
            },
            clear=False,
        ):
            service = EmailService()

        self.assertFalse(service.request_kwargs.get("verify"))

    def test_resolve_email_id_supports_cursor_paging(self):
        service = self._new_service()
        target = "demo@example.com"
        first_page = {"emails": [], "nextCursor": "next-1"}
        second_page = {"emails": [{"id": "email-id-1", "address": target}]}

        with patch(
            "g.email_service.requests.request",
            side_effect=[
                self._fake_response(200, first_page),
                self._fake_response(200, second_page),
            ],
        ):
            email_id = service._resolve_email_id(target)

        self.assertEqual(email_id, "email-id-1")

    def test_fetch_verification_code_uses_message_detail(self):
        service = self._new_service()

        with patch.object(service, "_resolve_email_id", return_value="email-id-1"), patch.object(
            service,
            "_list_email_messages",
            return_value=([{"id": "msg-1", "subject": "Code"}], None),
        ), patch.object(
            service,
            "_get_message_detail",
            return_value={"content": "Your verification code is 12-34-56"},
        ):
            code = service.fetch_verification_code("demo@example.com", max_attempts=1)

        self.assertEqual(code, "123456")

    def test_fetch_verification_code_skips_excluded_codes(self):
        service = self._new_service()

        with patch.object(service, "_resolve_email_id", return_value="email-id-1"), patch.object(
            service,
            "_list_email_messages",
            return_value=(
                [
                    {"id": "msg-1", "subject": "Code", "received_at": 2},
                    {"id": "msg-2", "subject": "Code", "received_at": 1},
                ],
                None,
            ),
        ), patch.object(
            service,
            "_get_message_detail",
            side_effect=[
                {"content": "Your verification code is 12-34-56"},
                {"content": "Your verification code is 98-76-54"},
            ],
        ):
            code = service.fetch_verification_code(
                "demo@example.com",
                max_attempts=1,
                exclude_codes={"123456"},
            )

        self.assertEqual(code, "987654")

    def test_delete_email_checks_success_flag(self):
        service = self._new_service()
        with patch.object(service, "_resolve_email_id", return_value="email-id-1"), patch(
            "g.email_service.requests.request",
            side_effect=[
                self._fake_response(200, {"success": False}),
                self._fake_response(200, {"success": True}),
            ],
        ):
            ok = service.delete_email("demo@example.com")

        self.assertTrue(ok)

    def test_create_email_uses_one_day_expiry_by_default(self):
        service = self._new_service()
        captured_json = []

        def _fake_request(**kwargs):
            if kwargs.get("method") == "GET" and kwargs.get("url", "").endswith("/api/config"):
                return self._fake_response(200, {"emailDomains": ["mtmc.top"]})
            if kwargs.get("method") == "POST" and kwargs.get("url", "").endswith("/api/emails/generate"):
                captured_json.append(kwargs.get("json"))
                return self._fake_response(200, {"email": "demo@mtmc.top", "id": "email-id-1"})
            return self._fake_response(500, {})

        with patch("g.email_service.requests.request", side_effect=_fake_request):
            _, email = service.create_email()

        self.assertEqual(email, "demo@mtmc.top")
        self.assertTrue(captured_json)
        self.assertEqual(captured_json[0].get("expiryTime"), EmailService.DEFAULT_EMAIL_EXPIRY_MS)


if __name__ == "__main__":
    unittest.main()
