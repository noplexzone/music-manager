from __future__ import annotations

import base64
from functools import lru_cache

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Fixed application salt — keeps derivation deterministic across restarts.
# The SECRET_KEY is the actual secret; the salt just domain-separates this use.
# Do not change this byte string: existing encrypted settings were derived with it,
# and even a rename-only update would make every stored secret undecryptable.
_SALT = b"music-manager-settings-v1"
_ITERATIONS = 200_000


@lru_cache(maxsize=4)
def _fernet(secret_key: str) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
    return Fernet(key)


def encrypt_secret(value: str, secret_key: str) -> str:
    """Encrypt *value* with an authenticated Fernet cipher derived from *secret_key*."""
    return _fernet(secret_key).encrypt(value.encode()).decode()


def decrypt_secret(token: str, secret_key: str) -> str:
    """Decrypt and authenticate *token*; raises on tampered or wrong-key input."""
    return _fernet(secret_key).decrypt(token.encode()).decode()
