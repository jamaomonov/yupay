"""The machine-API credential format and request-signature scheme (spec §9.2).

The **one home** for the wire format third parties implement against — the
same rule ``pricing.py`` follows for the wholesale price formula. Nothing
else in the codebase may re-derive a canonical string or a digest; the
integration guide in this module's README is prose written from these
functions, and the two must never drift.

Pure: no DB, no settings, no FastAPI. ``service`` mints keys with it and
``auth`` verifies with it, and both can be tested without either.

## Why the stored value is also the signing key

The credential is a public ``key_id`` plus a secret shown exactly once. The
secret itself is never stored — only its SHA-256 digest, in
``merchant_api_keys.secret_hash``. An HMAC, though, cannot be verified
without the key material, so the digest *is* what both sides key the HMAC
with:

    signing_key = sha256_hex(secret)     # 64 lowercase hex chars
    signature   = hex(HMAC_SHA256(signing_key, canonical_message))

This is the only reading of "stored only as SHA-256" that a challenge-free
signature scheme admits, and it is worth being explicit about what it does
and does not buy. It does NOT make a database dump harmless: whoever holds
``secret_hash`` can sign requests, exactly as if we stored the secret in the
clear. What it buys is that the secret string the merchant pasted into their
own configuration is not recoverable from our database, so a dump cannot be
replayed against anything *else* they used it for. The controls that matter
against a dump are revocation (``revoked_at``) and the per-key IP allowlist.

The alternative — storing the secret reversibly encrypted (the
``inventory.crypto`` pattern) so the documented ``HMAC(secret, …)`` holds
literally — needs a second column and therefore a migration, which this task
is explicitly not to write.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

#: Public half. Prefixed so a leaked value is greppable and obviously ours,
#: the convention every provider follows (``sk_live_``, ``ghp_``).
KEY_ID_PREFIX = "ypm_"

#: Private half. A different prefix from the key id so the two cannot be
#: swapped by a merchant reading their own config file.
SECRET_PREFIX = "ypms_"  # noqa: S105  # a prefix, not a credential

#: Bytes of entropy behind each half. 24 raw bytes → 32 url-safe characters
#: for the id (plus the prefix, 36 of the column's 48); 32 raw bytes → 256
#: bits for the secret, which is why no slow hash is needed anywhere here.
_KEY_ID_BYTES = 24
_SECRET_BYTES = 32


def new_key_id() -> str:
    """Mint a public key id.

    Returns:
        A ``ypm_``-prefixed, url-safe identifier that fits
        ``merchant_api_keys.key_id`` (``String(48)``).
    """
    return KEY_ID_PREFIX + secrets.token_urlsafe(_KEY_ID_BYTES)


def new_secret() -> str:
    """Mint a request-signing secret. Returned to the merchant exactly once.

    Returns:
        A ``ypms_``-prefixed, url-safe secret carrying 256 bits of entropy.
    """
    return SECRET_PREFIX + secrets.token_urlsafe(_SECRET_BYTES)


def derive_signing_key(secret: str) -> str:
    """Derive the HMAC key stored in ``secret_hash`` from a secret.

    See the module docstring for why the stored digest is also the signing
    key. Both sides run this: we at issuance, the merchant on every request.

    Args:
        secret: The secret handed to the merchant, verbatim.

    Returns:
        64 lowercase hex characters — exactly the width of ``secret_hash``.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def canonical_message(*, timestamp: str, method: str, path: str, body: bytes) -> bytes:
    """Build the byte string that gets signed.

    ``f"{timestamp}\\n{method}\\n{path}\\n{body}"`` — the timestamp exactly as
    it appears in the header (not re-formatted from an int, so a client that
    sends ``"01757000000"`` signs and we verify the same characters), the
    method upper-cased, the URL path **without** the query string, and then
    the raw request body appended verbatim. An empty body contributes
    nothing after the final newline.

    Args:
        timestamp: The ``X-Merchant-Timestamp`` value, as sent.
        method: HTTP method; upper-cased here so ``get`` and ``GET`` agree.
        path: The request path, percent-decoded, query string excluded.
        body: The raw request body bytes; ``b""`` for a GET.

    Returns:
        The message to run HMAC-SHA256 over.
    """
    return f"{timestamp}\n{method.upper()}\n{path}\n".encode() + body


def expected_signature(signing_key: str, message: bytes) -> str:
    """Compute the signature we expect for ``message``.

    Args:
        signing_key: The 64-hex-character key from :func:`derive_signing_key`.
        message: The output of :func:`canonical_message`.

    Returns:
        Lowercase hex HMAC-SHA256.
    """
    return hmac.new(signing_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def signature_matches(signing_key: str, message: bytes, provided: str) -> bool:
    """Constant-time compare of a client signature against the expected one.

    ``provided`` is trimmed and lower-cased first: whitespace and hex case
    are not secrets, and normalising them turns two common integration bugs
    into successes instead of an opaque 401. The comparison itself is
    ``hmac.compare_digest`` (spec §9.2).

    Args:
        signing_key: The 64-hex-character key from :func:`derive_signing_key`.
        message: The output of :func:`canonical_message`.
        provided: The ``X-Merchant-Signature`` header value.

    Returns:
        Whether the signature is valid.
    """
    return hmac.compare_digest(expected_signature(signing_key, message), provided.strip().lower())


__all__ = [
    "KEY_ID_PREFIX",
    "SECRET_PREFIX",
    "canonical_message",
    "derive_signing_key",
    "expected_signature",
    "new_key_id",
    "new_secret",
    "signature_matches",
]
