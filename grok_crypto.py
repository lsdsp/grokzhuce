import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


_SSO_ENCRYPTION_PREFIX = "enc-v1"
_KDF_ITERATIONS = 600_000
_SALT_SIZE = 16


def _derive_fernet_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def encrypt_sso_value(value: str, passphrase: str) -> str:
    if not passphrase:
        raise ValueError("Missing SSO_ENCRYPTION_PASSPHRASE")
    salt = os.urandom(_SALT_SIZE)
    token = Fernet(_derive_fernet_key(passphrase, salt)).encrypt(value.encode("utf-8")).decode("utf-8")
    salt_text = base64.urlsafe_b64encode(salt).decode("ascii")
    return f"{_SSO_ENCRYPTION_PREFIX}:{salt_text}:{token}"


def decrypt_sso_value(value: str, passphrase: str) -> str:
    if not passphrase:
        raise ValueError("Missing SSO_ENCRYPTION_PASSPHRASE")
    prefix, salt_text, token = value.split(":", 2)
    if prefix != _SSO_ENCRYPTION_PREFIX:
        raise ValueError("Unsupported encrypted SSO payload format")
    salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
    data = Fernet(_derive_fernet_key(passphrase, salt)).decrypt(token.encode("utf-8"))
    return data.decode("utf-8")
