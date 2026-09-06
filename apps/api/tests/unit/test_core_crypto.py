"""``core.crypto`` — the purpose-separated SecretBox primitive (M2, Task 2).

Lifted out of ``modules/inventory/crypto.py`` so merchant API secrets can be
encrypted at rest without sharing a key with voucher codes. The property that
matters is the separation: same input key material, independent per-purpose
keys.
"""

from __future__ import annotations

import pytest
from nacl.exceptions import CryptoError
from yupay.core import crypto


def test_round_trip() -> None:
    secret = "ypms_a-secret-with-ünicode-and-symbols-!@#"
    ciphertext, nonce = crypto.encrypt(secret, purpose=crypto.PURPOSE_MERCHANT_API_KEY)
    assert secret.encode() not in ciphertext
    assert len(nonce) == crypto.NONCE_SIZE
    assert crypto.decrypt(ciphertext, nonce, purpose=crypto.PURPOSE_MERCHANT_API_KEY) == secret


def test_each_encryption_uses_a_fresh_nonce() -> None:
    first, first_nonce = crypto.encrypt("x", purpose=crypto.PURPOSE_MERCHANT_API_KEY)
    second, second_nonce = crypto.encrypt("x", purpose=crypto.PURPOSE_MERCHANT_API_KEY)
    assert first_nonce != second_nonce
    assert first != second


def test_purposes_are_cryptographically_separated() -> None:
    """The whole point: one input key, independent per-purpose keys."""
    ciphertext, nonce = crypto.encrypt("x", purpose=crypto.PURPOSE_MERCHANT_API_KEY)
    with pytest.raises(CryptoError):
        crypto.decrypt(ciphertext, nonce, purpose="yupay:something-else:v1")

    ikm = b"\x01" * 32
    assert crypto.derive_key(ikm, crypto.PURPOSE_MERCHANT_API_KEY) != crypto.derive_key(
        ikm, "yupay:something-else:v1"
    )


def test_a_tampered_ciphertext_does_not_open() -> None:
    """Poly1305 is what makes a hand-edited row a clean failure, not garbage."""
    ciphertext, nonce = crypto.encrypt("x", purpose=crypto.PURPOSE_MERCHANT_API_KEY)
    tampered = bytes([ciphertext[0] ^ 0xFF]) + ciphertext[1:]
    with pytest.raises(CryptoError):
        crypto.decrypt(tampered, nonce, purpose=crypto.PURPOSE_MERCHANT_API_KEY)


def test_the_wrong_nonce_does_not_open() -> None:
    ciphertext, _ = crypto.encrypt("x", purpose=crypto.PURPOSE_MERCHANT_API_KEY)
    with pytest.raises(CryptoError):
        crypto.decrypt(
            ciphertext, b"\x00" * crypto.NONCE_SIZE, purpose=crypto.PURPOSE_MERCHANT_API_KEY
        )
