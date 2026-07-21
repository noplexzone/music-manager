from __future__ import annotations

import pytest

from app.crypto import decrypt_secret, encrypt_secret


def test_encrypt_decrypt_roundtrip() -> None:
    plaintext = "super-secret-api-key"
    ciphertext = encrypt_secret(plaintext, "my-secret-key")
    assert decrypt_secret(ciphertext, "my-secret-key") == plaintext


def test_encrypted_value_does_not_contain_plaintext() -> None:
    plaintext = "very-secret-value"
    ciphertext = encrypt_secret(plaintext, "app-secret")
    assert plaintext not in ciphertext


def test_different_keys_produce_different_ciphertexts() -> None:
    plaintext = "same-plaintext"
    ct1 = encrypt_secret(plaintext, "key-one")
    ct2 = encrypt_secret(plaintext, "key-two")
    assert ct1 != ct2


def test_wrong_key_raises_on_decrypt() -> None:
    ciphertext = encrypt_secret("secret", "correct-key")
    from cryptography.fernet import InvalidToken

    with pytest.raises(InvalidToken):
        decrypt_secret(ciphertext, "wrong-key")


def test_encrypt_returns_string() -> None:
    result = encrypt_secret("value", "key")
    assert isinstance(result, str)
    assert len(result) > 0


def test_decrypt_returns_string() -> None:
    token = encrypt_secret("hello", "key")
    result = decrypt_secret(token, "key")
    assert isinstance(result, str)
