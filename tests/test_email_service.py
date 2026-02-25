import unittest

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


if __name__ == "__main__":
    unittest.main()
