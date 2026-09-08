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

## The outgoing-webhook signature (M3a, spec §10)

The same scheme pointed the other way: we sign, the merchant verifies, keyed
by the ``ypmw_`` secret rather than the ``ypms_`` one. Four fields:

    {timestamp}\\n{delivery_id}\\n{event_type}\\n{hex(sha256(body))}

sent as ``X-Yupay-Timestamp`` / ``X-Yupay-Delivery`` / ``X-Yupay-Event`` /
``X-Yupay-Signature`` beside the JSON body. The shape is load-bearing for the
same reason as above — every field is either fixed-width or cannot contain the
separator, so no value can be spelled to move a field boundary:

- ``timestamp`` is ASCII digits (Unix seconds);
- ``delivery_id`` is a UUID, and it is in the **signed** material rather than
  only in a header. It is the receiver's dedupe handle, and a webhook is
  at-least-once: a retry after a lost ``200`` is indistinguishable from a
  genuine second transition unless something stable identifies the attempt.
  An unsigned header cannot do that job against a replay;
- ``event_type`` comes from ``webhooks.EVENT_TYPES``, a closed two-value
  vocabulary of ASCII dotted names;
- the body is a **hash**, so a payload full of newlines shifts nothing.

There is no query string and no method field: a webhook is always a ``POST``
to the merchant's one configured URL, and the URL is not signed because they
already know which endpoint received the request.
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

#: The **outgoing-webhook** signing secret (M3a). A third prefix for the same
#: reason there is a second one: a merchant holds both at once, they key
#: opposite directions of the same integration, and a config file that mixes
#: them up should fail visibly rather than produce a signature nobody can
#: explain.
WEBHOOK_SECRET_PREFIX = "ypmw_"  # noqa: S105  # a prefix, not a credential

#: The four headers one outgoing delivery carries. Named here rather than at
#: the sender because they are wire format a third party implements against —
#: the same rule that keeps the canonical string in this module. The
#: ``X-Yupay-`` family (matching the storefront's existing ``X-Yupay-Surface``)
#: is deliberately **not** the inbound ``X-Merchant-`` one: a merchant holds
#: both credentials at once, they key opposite directions of one integration,
#: and two header families that cannot be confused is the same reasoning as the
#: two secret prefixes above.
WEBHOOK_DELIVERY_HEADER = "X-Yupay-Delivery"
WEBHOOK_EVENT_HEADER = "X-Yupay-Event"
WEBHOOK_TIMESTAMP_HEADER = "X-Yupay-Timestamp"
WEBHOOK_SIGNATURE_HEADER = "X-Yupay-Signature"

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


def new_webhook_secret() -> str:
    """Mint an outgoing-webhook signing secret. Returned to the merchant once.

    Same 256 bits as :func:`new_secret` and minted here for the same reason:
    this module is the one home for the credential format, so a second
    ``secrets.token_urlsafe`` call elsewhere is how two halves of one scheme
    start disagreeing about entropy.

    Returns:
        A ``ypmw_``-prefixed, url-safe secret carrying 256 bits of entropy.
    """
    return WEBHOOK_SECRET_PREFIX + secrets.token_urlsafe(_SECRET_BYTES)


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


def webhook_canonical_message(
    *, timestamp: str, delivery_id: str, event_type: str, body: bytes
) -> bytes:
    """Build the byte string one outgoing delivery is signed over.

    See the module docstring for why these four fields and why the delivery id
    is among them rather than only in a header.

    Args:
        timestamp: The ``X-Yupay-Timestamp`` value exactly as sent — Unix
            seconds as ASCII digits, and the same characters we put on the
            wire, so a verifier re-signs what it received.
        delivery_id: The ``merchant_webhook_deliveries`` row id. Stable across
            every retry of that row, which is what makes it a dedupe handle.
        event_type: One of ``webhooks.EVENT_TYPES``.
        body: The exact JSON bytes being POSTed.

    Returns:
        The message to run HMAC-SHA256 over with the merchant's ``ypmw_``
        secret.
    """
    return (f"{timestamp}\n{delivery_id}\n{event_type}\n{body_digest(body)}").encode()


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

    A malformed header returns here *before* the HMAC is computed, so it is
    cheaper than a well-formed wrong one. That difference leaks nothing about
    the credential: the header's shape is attacker-supplied input they already
    know. The equalisation that does matter — unknown and revoked keys hashing
    against a dummy secret — happens in :mod:`.auth`.

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
    "WEBHOOK_DELIVERY_HEADER",
    "WEBHOOK_EVENT_HEADER",
    "WEBHOOK_SECRET_PREFIX",
    "WEBHOOK_SIGNATURE_HEADER",
    "WEBHOOK_TIMESTAMP_HEADER",
    "body_digest",
    "canonical_message",
    "expected_signature",
    "new_key_id",
    "new_secret",
    "new_webhook_secret",
    "signature_matches",
    "webhook_canonical_message",
]
