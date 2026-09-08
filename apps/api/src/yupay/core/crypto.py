"""Symmetric encryption for application secrets at rest, parameterised by purpose.

XSalsa20-Poly1305 via ``nacl.secret.SecretBox``, one random nonce per row.
The primitive ``modules/inventory/crypto.py`` grew for voucher codes, lifted
to ``core`` and given a **purpose label** so a second concern can use it
without sharing a key with the first.

## Key material

There is one input key — ``INVENTORY_ENC_KEY`` — and every purpose gets its
own HKDF-derived key from it, domain-separated by an ``info`` label. That is
the trick ``inventory.crypto`` already uses to keep its ``code_hash`` HMAC key
independent of its SecretBox key; here it does the same job across modules, so
compromising one purpose's key does not hand over another's.

Reusing that env var rather than minting a new one is deliberate: a new
variable has to be provisioned on production by hand, and every deployment
that missed it would fail to start. HKDF separation buys the same isolation
for free.

**The variable's name is now narrower than its job.** A neutral rename
(``APP_ENC_KEY``, with ``INVENTORY_ENC_KEY`` accepted as a deprecated alias
for one release) is a follow-up, not this module's business.

## What this does and does not buy

A database dump alone no longer yields anything usable — ciphertext without
the key is inert. An attacker who holds **both** the dump and the application
key is exactly as well off as if the secret were stored in the clear. That is
the honest boundary: this defends against a stolen backup, a leaked replica,
or a SQL-injection read, not against a compromised application host.

Dev and test derive a deterministic key from the JWT email pepper so the suite
needs no extra setup; production with an empty key **raises at first use**
rather than silently encrypting under a guessable key.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from nacl.secret import SecretBox

from yupay.core.config import Settings, get_settings

#: Nonce width, re-exported so callers need not import nacl to size a column.
NONCE_SIZE = SecretBox.NONCE_SIZE

#: Purpose label for merchant machine-API secrets. Versioned: changing the
#: cipher or the encoding means a new label, not a silent reinterpretation of
#: existing rows.
PURPOSE_MERCHANT_API_KEY = "yupay:merchants:apikey:v1"

#: Purpose label for merchant **outgoing-webhook** signing secrets (M3a).
#: A separate label from :data:`PURPOSE_MERCHANT_API_KEY` on purpose: the two
#: secrets protect opposite directions — one authenticates a reseller calling
#: us, the other authenticates us calling a reseller — and HKDF separation
#: means compromising the key behind either one does not read the other's
#: rows. Same reasoning that keeps voucher codes off the merchant key.
PURPOSE_MERCHANT_WEBHOOK = "yupay:merchants:webhook:v1"


def _derive_dev_key(seed: str) -> bytes:
    """Deterministic dev/test key. Never reached when ``is_prod``."""
    return hashlib.sha256(("yupay-inventory:" + seed).encode("utf-8")).digest()


def input_key_material(settings: Settings) -> bytes:
    """The raw 32-byte input key every purpose is derived from.

    Args:
        settings: The app settings to read ``INVENTORY_ENC_KEY`` from.

    Returns:
        32 bytes of input key material.

    Raises:
        RuntimeError: In production with no key configured, or when the
            configured value is not 32 bytes of base64.
    """
    raw = settings.inventory_enc_key or ""
    if not raw:
        if settings.is_prod:
            raise RuntimeError("INVENTORY_ENC_KEY is required in production — refusing to start.")
        return _derive_dev_key(settings.auth_email_pepper or "dev")
    # Accept either urlsafe or standard base64; tolerate missing padding.
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


def derive_key(ikm: bytes, purpose: str) -> bytes:
    """HKDF-SHA256 a purpose-specific key from the input key material.

    Args:
        ikm: The input key material from :func:`input_key_material`.
        purpose: The domain-separation label, e.g.
            :data:`PURPOSE_MERCHANT_API_KEY`.

    Returns:
        A 32-byte key independent of every other purpose's.
    """
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=purpose.encode("utf-8"))
    return hkdf.derive(ikm)


@lru_cache(maxsize=8)
def box_for(purpose: str) -> SecretBox:
    """The cached ``SecretBox`` for one purpose.

    Args:
        purpose: The domain-separation label.

    Returns:
        A box keyed by this purpose's derived key.
    """
    return SecretBox(derive_key(input_key_material(get_settings()), purpose))


def encrypt(plaintext: str, *, purpose: str) -> tuple[bytes, bytes]:
    """Encrypt a secret under ``purpose``'s key.

    Args:
        plaintext: The secret. UTF-8 encoded before encryption.
        purpose: The domain-separation label.

    Returns:
        ``(ciphertext, nonce)``. The nonce is stored beside the ciphertext,
        not prepended to it — the same shape ``inventory_codes`` uses.
    """
    nonce = secrets.token_bytes(SecretBox.NONCE_SIZE)
    # ``SecretBox.encrypt`` returns nonce + ciphertext; we store them in
    # separate columns, so peel off the ciphertext-with-MAC part.
    return box_for(purpose).encrypt(plaintext.encode("utf-8"), nonce).ciphertext, nonce


def decrypt(ciphertext: bytes, nonce: bytes, *, purpose: str) -> str:
    """Decrypt a secret encrypted under ``purpose``'s key.

    Args:
        ciphertext: The stored ciphertext (with its Poly1305 tag).
        nonce: The stored nonce.
        purpose: The domain-separation label used at encryption time.

    Returns:
        The plaintext secret.

    Raises:
        nacl.exceptions.CryptoError: If the key is wrong or the row was
            tampered with — the MAC is what makes that detectable.
    """
    return box_for(purpose).decrypt(ciphertext, nonce).decode("utf-8")


__all__ = [
    "NONCE_SIZE",
    "PURPOSE_MERCHANT_API_KEY",
    "PURPOSE_MERCHANT_WEBHOOK",
    "box_for",
    "decrypt",
    "derive_key",
    "encrypt",
    "input_key_material",
]
