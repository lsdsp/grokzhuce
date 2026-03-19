import unittest

from grok_crypto import decrypt_sso_value, encrypt_sso_value


class GrokCryptoTests(unittest.TestCase):
    def test_encrypt_and_decrypt_roundtrip(self):
        token = "sso-token-abcdef123456"
        passphrase = "correct horse battery staple"

        encrypted = encrypt_sso_value(token, passphrase)

        self.assertNotEqual(encrypted, token)
        self.assertTrue(encrypted.startswith("enc-v1:"))
        self.assertEqual(decrypt_sso_value(encrypted, passphrase), token)


if __name__ == "__main__":
    unittest.main()
