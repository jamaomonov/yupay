"""Unit tests for ``inventory.crypto.code_hash``.

``code_hash`` used to be a bare, unsalted ``sha256(plaintext)`` — anyone who
read a leaked ``inventory_codes`` row could brute-force low-entropy voucher
codes offline. It is now a keyed HMAC-SHA256, with the key HKDF-derived from
``INVENTORY_ENC_KEY``. These tests pin down the properties that matter: the
digest is still deterministic (dedup keeps working), it's no longer equal to
a bare SHA-256, and it actually depends on the server-side key material (i.e.
it is *keyed*, not just renamed).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

import pytest
from yupay.core.config import get_settings
from yupay.modules.inventory import crypto


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    """Clear both the settings cache and the derived-key cache around each test.

    ``crypto._hash_key`` is ``lru_cache``d on top of ``get_settings()``, same
    pattern as ``crypto.get_box`` — changing env vars mid-test-session
    requires clearing both, or the cached key from a previous test lingers.
    """
    get_settings.cache_clear()
    crypto._hash_key.cache_clear()
    yield
    get_settings.cache_clear()
    crypto._hash_key.cache_clear()


def test_code_hash_is_deterministic() -> None:
    assert crypto.code_hash("VOUCHER-CODE-1234") == crypto.code_hash("VOUCHER-CODE-1234")


def test_code_hash_is_64_char_lowercase_hex() -> None:
    digest = crypto.code_hash("VOUCHER-CODE-1234")
    assert len(digest) == 64
    assert digest == digest.lower()
    int(digest, 16)  # raises ValueError if not valid hex


def test_code_hash_differs_from_bare_sha256() -> None:
    """The whole point of the fix: no longer a bare, unkeyed digest."""
    plaintext = "VOUCHER-CODE-1234"
    assert crypto.code_hash(plaintext) != hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def test_code_hash_is_keyed_off_server_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Changing the server-side key material changes the digest.

    This is what distinguishes a keyed hash from a relabeled unsalted one: an
    attacker without the key can't reproduce the digest, and here we prove
    the digest actually depends on it.
    """
    monkeypatch.setenv("AUTH_EMAIL_PEPPER", "pepper-one")
    get_settings.cache_clear()
    crypto._hash_key.cache_clear()
    digest_a = crypto.code_hash("VOUCHER-CODE-1234")

    monkeypatch.setenv("AUTH_EMAIL_PEPPER", "pepper-two")
    get_settings.cache_clear()
    crypto._hash_key.cache_clear()
    digest_b = crypto.code_hash("VOUCHER-CODE-1234")

    assert digest_a != digest_b


def test_code_hash_different_plaintexts_differ() -> None:
    assert crypto.code_hash("CODE-A") != crypto.code_hash("CODE-B")
