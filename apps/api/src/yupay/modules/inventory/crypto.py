"""Symmetric encryption for voucher / coupon codes at rest.

XSalsa20-Poly1305 via ``nacl.secret.SecretBox``. Each row carries its own nonce.

Key sources:
- ``INVENTORY_ENC_KEY`` env var (base64, urlsafe or standard, 32 bytes).
- In dev/test, an empty key derives a deterministic dev-only key from the JWT
  email pepper so the test suite doesn't need extra setup.
- In production with an empty key, the helper raises — see :func:`get_box`.

``code_hash`` reuses the same ``INVENTORY_ENC_KEY`` input key material, but
HKDF-derives a *separate* HMAC key from it (distinct ``info`` label) rather
than encrypting with it directly, so a compromise of one purpose doesn't hand
over the other for free.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from nacl.secret import SecretBox

from yupay.core.config import Settings, get_settings


def _derive_dev_key(seed: str) -> bytes:
    return hashlib.sha256(("yupay-inventory:" + seed).encode("utf-8")).digest()


def _key_bytes(settings: Settings) -> bytes:
    raw = settings.inventory_enc_key or ""
    if not raw:
        if settings.is_prod:
            raise RuntimeError("INVENTORY_ENC_KEY is required in production — refusing to start.")
        seed = settings.auth_email_pepper or "dev"
        return _derive_dev_key(seed)
    # Accept either urlsafe or standard base64; tolerate a missing padding.
    cleaned = raw.strip().replace("-", "+").replace("_", "/")
    padding = "=" * (-len(cleaned) % 4)
    try:
        key = base64.b64decode(cleaned + padding, validate=False)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise RuntimeError("INVENTORY_ENC_KEY is not valid base64") from exc
    if len(key) != SecretBox.KEY_SIZE:
        raise RuntimeError(
            f"INVENTORY_ENC_KEY must decode to {SecretBox.KEY_SIZE} bytes; got {len(key)}"
        )
    return key


@lru_cache(maxsize=1)
def get_box() -> SecretBox:
    return SecretBox(_key_bytes(get_settings()))


def encrypt(plaintext: str) -> tuple[bytes, bytes]:
    """Encrypt a code string. Returns ``(ciphertext, nonce)``."""
    box = get_box()
    nonce = _random_nonce()
    enc = box.encrypt(plaintext.encode("utf-8"), nonce)
    # ``SecretBox.encrypt`` returns ``EncryptedMessage`` (nonce + ciphertext). We
    # store nonce separately, so peel the ciphertext-with-mac part.
    return enc.ciphertext, nonce


def decrypt(ciphertext: bytes, nonce: bytes) -> str:
    box = get_box()
    return box.decrypt(ciphertext, nonce).decode("utf-8")


def _random_nonce() -> bytes:
    import secrets

    return secrets.token_bytes(SecretBox.NONCE_SIZE)


_HASH_KEY_INFO = b"yupay-inventory:code-hash:v1"


def _derive_hash_key(ikm: bytes) -> bytes:
    """HKDF-derive the ``code_hash`` HMAC key from the encryption key material.

    ``info`` domain-separates this from the SecretBox key derived from the
    same ``ikm`` in :func:`get_box`, so the two keys are cryptographically
    independent even though they trace back to the same secret.
    """
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HASH_KEY_INFO)
    return hkdf.derive(ikm)


@lru_cache(maxsize=1)
def _hash_key() -> bytes:
    return _derive_hash_key(_key_bytes(get_settings()))


def code_hash(plaintext: str) -> str:
    """Lower-case hex HMAC-SHA256, keyed off ``INVENTORY_ENC_KEY``.

    Used for dedup only — one-way, never reversed. Keying the digest (instead
    of a bare ``sha256(plaintext)``) means a leaked ``inventory_codes`` table
    can't be brute-forced offline against low-entropy voucher codes without
    also recovering the server-side key.
    """
    return hmac.new(_hash_key(), plaintext.encode("utf-8"), hashlib.sha256).hexdigest()


__all__ = ["code_hash", "decrypt", "encrypt", "get_box"]
