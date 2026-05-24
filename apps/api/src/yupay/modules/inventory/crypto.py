"""Symmetric encryption for voucher / coupon codes at rest.

XSalsa20-Poly1305 via ``nacl.secret.SecretBox``. Each row carries its own nonce.

Key sources:
- ``INVENTORY_ENC_KEY`` env var (base64, urlsafe or standard, 32 bytes).
- In dev/test, an empty key derives a deterministic dev-only key from the JWT
  email pepper so the test suite doesn't need extra setup.
- In production with an empty key, the helper raises — see :func:`get_box`.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

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


def code_hash(plaintext: str) -> str:
    """Lower-case hex SHA-256. Used for dedup; one-way, never reversed."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


__all__ = ["code_hash", "decrypt", "encrypt", "get_box"]
