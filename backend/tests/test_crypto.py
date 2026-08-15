"""Credential encryption."""

import pytest

from app.core.crypto import DecryptionError, decrypt, encrypt, generate_key


def test_roundtrip_returns_the_original() -> None:
    assert decrypt(encrypt("s3cret-password")) == "s3cret-password"


def test_ciphertext_does_not_contain_the_plaintext() -> None:
    assert "s3cret-password" not in encrypt("s3cret-password")


def test_same_plaintext_encrypts_differently_each_time() -> None:
    # Fernet includes a random IV, so identical passwords are not linkable.
    assert encrypt("same") != encrypt("same")


def test_unicode_survives_the_roundtrip() -> None:
    secret = "pa$$wörd-日本語-🔐"
    assert decrypt(encrypt(secret)) == secret


def test_empty_string_roundtrips() -> None:
    assert decrypt(encrypt("")) == ""


def test_tampered_ciphertext_is_rejected() -> None:
    token = encrypt("s3cret-password")
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")

    with pytest.raises(DecryptionError):
        decrypt(tampered)


def test_garbage_input_raises_a_clear_error() -> None:
    with pytest.raises(DecryptionError, match="could not be decrypted"):
        decrypt("not-a-fernet-token")


def test_generated_key_is_usable() -> None:
    from cryptography.fernet import Fernet

    Fernet(generate_key().encode())
