"""Unit tests for password hashing and JWT handling."""

from datetime import timedelta

import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_is_not_the_plaintext() -> None:
    hashed = hash_password("correct-horse-battery")
    assert hashed != "correct-horse-battery"
    assert hashed.startswith("$2")


def test_hashes_are_salted_and_therefore_differ() -> None:
    assert hash_password("same-password") != hash_password("same-password")


def test_verify_accepts_the_right_password() -> None:
    assert verify_password("s3cret-password", hash_password("s3cret-password"))


def test_verify_rejects_the_wrong_password() -> None:
    assert not verify_password("wrong", hash_password("s3cret-password"))


def test_verify_rejects_a_malformed_hash_without_raising() -> None:
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_overlong_password_is_refused_rather_than_truncated() -> None:
    with pytest.raises(ValueError):
        hash_password("a" * 73)


def test_token_roundtrips_subject_and_claims() -> None:
    token = create_access_token("user-123", role="admin")
    payload = decode_access_token(token)

    assert payload is not None
    assert payload["sub"] == "user-123"
    assert payload["role"] == "admin"


def test_expired_token_is_rejected() -> None:
    token = create_access_token("user-123", expires_delta=timedelta(seconds=-10))
    assert decode_access_token(token) is None


def test_tampered_token_is_rejected() -> None:
    token = create_access_token("user-123")
    assert decode_access_token(token + "x") is None
