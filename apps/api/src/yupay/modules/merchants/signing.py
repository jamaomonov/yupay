"""The machine-API credential format and request-signature scheme (spec §9.2).

The **one home** for the wire format third parties implement against — the
same rule ``pricing.py`` follows for the wholesale price formula. Nothing
else in the codebase may re-derive a canonical string or a digest; the
integration guide in this module's README is prose written from these
functions, and the two must never drift.

Pure: no DB, no settings, no FastAPI. ``service`` mints keys with it and
``auth`` verifies with it, and both can be tested without either.

## The scheme

An ordinary Stripe/AWS-shaped signature. The merchant holds a ``key_id`` and
a ``secret``; the secret's UTF-8 bytes key an HMAC-SHA256 directly — there is
no derivation step, nothing to get subtly wrong in another language. We can
do this because the secret is **encrypted** at rest (``core.crypto``), not
hashed: an HMAC cannot be verified without the key material, and a scheme
that stores a digest and then signs with that digest is storing key material
in the clear under a reassuring name.

## The canonical string

    {timestamp}\\n{METHOD}\\n{raw_path}\\n{raw_query}\\n{hex(sha256(body))}

Five fields, and the shape is load-bearing:

- ``raw_path`` and ``raw_query`` are the bytes **exactly as they appear on
  the request line**, percent-encoded. Because they are percent-encoded by
  construction, neither can contain a literal LF, so the field boundaries
  cannot be forged: no request can smuggle a newline into one field and have
  a verifier read it as the start of the next. The earlier four-field form
  signed the *decoded* path and was safe only by accident — CPython's
  ``urlsplit`` happens to strip control characters — which is not a control.
- Signing the encoded form also removes the percent-decoding ambiguity for
  path segments a merchant chooses (``{merchant_order_id}``): there is one
  byte string on the wire and both sides sign it.
- The **query string is signed**. It carries ``limit`` / ``cursor`` /
  ``status`` / date filters, the edge access log records it verbatim, and the
  ±300 s window would otherwise make a lifted ``?limit=10`` replayable as
  ``?limit=100000``.
- The body is included as a **hash**, so every field is either fixed-width or
  LF-free and two distinct requests cannot produce identical signed bytes.

``\\n`` is a single LF (0x0A), never CRLF. Every string is UTF-8.
"""

from __future__ import annotations

import hashlib
import hmac
import re
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

#: A signature is exactly this: 64 lowercase hex characters. Validated
#: *before* ``compare_digest``, which raises ``TypeError`` on a non-ASCII
#: ``str`` — one raw high byte in the header would otherwise be an
#: unauthenticated 500 with a traceback, and would distinguish malformed
#: input from bad credentials, which this module promises never to do.
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")


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


def body_digest(body: bytes) -> str:
    """Lowercase hex SHA-256 of a request body. ``b""`` hashes like anything else.

    Args:
        body: The raw request body bytes.

    Returns:
        64 lowercase hex characters.
    """
    return hashlib.sha256(body).hexdigest()


def canonical_message(
    *, timestamp: str, method: str, raw_path: str, raw_query: str, body: bytes
) -> bytes:
    """Build the byte string that gets signed.

    Args:
        timestamp: The ``X-Merchant-Timestamp`` value exactly as sent — not
            re-formatted from an int, so a client sending ``"01725"`` signs
            and we verify the same characters.
        method: HTTP method; upper-cased here so ``get`` and ``GET`` agree.
        raw_path: The percent-encoded path from the request line, no query.
        raw_query: The raw query string, without ``?``; ``""`` when absent.
        body: The raw request body bytes; ``b""`` for a GET.

    Returns:
        The message to run HMAC-SHA256 over.
    """
    return (f"{timestamp}\n{method.upper()}\n{raw_path}\n{raw_query}\n{body_digest(body)}").encode()


def expected_signature(secret: str, message: bytes) -> str:
    """Compute the signature we expect for ``message``.

    Args:
        secret: The merchant's secret, verbatim; its UTF-8 bytes are the HMAC key.
        message: The output of :func:`canonical_message`.

    Returns:
        Lowercase hex HMAC-SHA256.
    """
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def signature_matches(secret: str, message: bytes, provided: str) -> bool:
    """Constant-time compare of a client signature against the expected one.

    ``provided`` is trimmed and lower-cased first — whitespace and hex case
    are not secrets, and normalising them turns two common integration bugs
    into successes rather than an opaque 401 — then **shape-checked against
    :data:`_HEX64` before any comparison**. That check is a correctness
    requirement, not tidiness: ``hmac.compare_digest`` raises ``TypeError``
    on a non-ASCII ``str``.

    The expected signature is still computed by the caller before this runs
    (see ``auth``'s timing note), so a malformed header costs the same as a
    wrong one.

    Args:
        secret: The merchant's secret.
        message: The output of :func:`canonical_message`.
        provided: The ``X-Merchant-Signature`` header value.

    Returns:
        Whether the signature is valid.
    """
    candidate = provided.strip().lower()
    if _HEX64.match(candidate) is None:
        return False
    return hmac.compare_digest(expected_signature(secret, message), candidate)


__all__ = [
    "KEY_ID_PREFIX",
    "SECRET_PREFIX",
    "body_digest",
    "canonical_message",
    "expected_signature",
    "new_key_id",
    "new_secret",
    "signature_matches",
]
