"""Unit tests for argon2id password hashing helpers."""

from __future__ import annotations

from yupay.modules.auth.security import hash_password, verify_password


def test_hash_is_argon2id_and_verifies() -> None:
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", h) is True


def test_verify_rejects_wrong_password() -> None:
    h = hash_password("s3cret-pass")
    assert verify_password("nope", h) is False


def test_hashes_are_salted_and_unique() -> None:
    assert hash_password("same") != hash_password("same")


def test_verify_handles_garbage_hash() -> None:
    assert verify_password("x", "not-a-hash") is False
