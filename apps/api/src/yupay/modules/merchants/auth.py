"""Signed-request authentication for the machine API ``/merchant/v1``.

The FastAPI dependency a reseller's server passes before any endpoint of the
machine API runs. Verifies the HMAC signature described in this module's
README (and built by ``signing``), then applies the account-level gates that
are not about the credential at all: the merchant's freeze state, the key's
optional IP allowlist, and the two-axis rate guard.

**Import this module directly, never through ``merchants.api``.** It binds to
``api.v1.deps.db_session`` so an endpoint's session and this dependency's are
the same session — which means importing it drags in the v1 package, and
re-exporting it from the facade would close a cycle for any service-layer
caller that imports ``merchants.api``. Exactly the rule ``admin_routes``
follows for its routers, and the same rule ``affiliate.routes`` documents.

## The order of checks, and why

1. **IP axis of the rate guard**, before anything is parsed — an unauthenticated
   flood must cost us one Redis INCR, not a database round-trip.
2. **Headers present**, **timestamp numeric and fresh**. These get their own
   error codes: a clock 400 seconds out is the single most common integration
   bug and telling the merchant so leaks nothing about any credential.
3. **The credential itself** — unknown key, revoked key and bad signature are
   one indistinguishable 401 (spec §9.2).
4. **Merchant axis of the rate guard**, charged on the key only once the
   signature has verified. See ``settings.merchant_api_key_rate_max``.
5. **Frozen merchant** → 403 ``merchant_frozen``; **IP allowlist** → 403
   ``ip_not_allowed``. Both are authenticated failures, so they are counted.
6. ``last_used_at``, best effort and throttled.

## Timing shape

Ruling: an early ``return`` on "no such key" is measurably faster than a real
HMAC comparison, which turns a 401 into an oracle for "this key id exists".
So the unknown- and revoked-key paths compute an HMAC against
``_DUMMY_SIGNING_KEY`` and compare it anyway before failing — the same shape
``auth.service.password_login`` uses for absent accounts. The three failures
also share one response body, so neither the timing nor the payload
discriminates.
"""

from __future__ import annotations

import contextlib
import ipaddress
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.client_ip import client_ip
from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.errors import ForbiddenError, RateLimitedError, UnauthorizedError
from yupay.modules.auth.ip_guard import guard_ip, hit_counter
from yupay.modules.merchants import signing
from yupay.modules.merchants.models import Merchant, MerchantApiKey

#: The three request headers. Documented in the module README, which is what
#: third parties implement against — renaming one is a breaking change to a
#: contract nobody but its owner can redeploy.
KEY_HEADER = "X-Merchant-Key"
TIMESTAMP_HEADER = "X-Merchant-Timestamp"
SIGNATURE_HEADER = "X-Merchant-Signature"

#: How far a request timestamp may sit from ours, either way (spec §9.2).
#: Bounds replay to a five-minute window; order creation is additionally
#: idempotent on ``merchant_order_id``, which is what makes a replay inside
#: the window harmless rather than merely unlikely.
TIMESTAMP_TOLERANCE_SECONDS = 300

#: The ``auth_ip_guard_bucket_max`` bucket charged for the IP axis.
RATE_BUCKET = "merchant-api"

#: Redis key for the merchant axis. Catalogued in
#: ``docs/architecture/cache-keys.md``.
_RATE_KEY = "merchants:apikey:{key_id}"

#: Machine-readable discriminators, echoed as ``code`` in the problem+json
#: body alongside RFC 7807's own ``type``. Spec §9.4 names the order-path
#: codes; these are the auth ones.
CODE_MISSING_CREDENTIALS = "missing_credentials"
CODE_STALE_TIMESTAMP = "stale_timestamp"
CODE_INVALID_CREDENTIALS = "invalid_credentials"
CODE_MERCHANT_FROZEN = "merchant_frozen"
CODE_IP_NOT_ALLOWED = "ip_not_allowed"

#: One body for unknown key / revoked key / bad signature — see "Timing shape".
_INVALID_DETAIL = "invalid merchant credentials"

#: Signed against when there is no usable key, so the work done is the same
#: whether or not the key id exists. Derived from a constant, not a secret.
_DUMMY_SIGNING_KEY = signing.derive_signing_key("merchant-auth-timing-parity")

#: Do not rewrite ``last_used_at`` more often than this. Without the guard
#: every request UPDATEs one row, and concurrent requests on the same key
#: then serialise on its row lock for the length of the whole transaction —
#: a throughput cliff on the one surface built for throughput. The column
#: answers "is this key still in use", which one write a minute answers just
#: as well.
_LAST_USED_MIN_INTERVAL = timedelta(seconds=60)


def address_allowed(allowlist: list[str] | None, address: str) -> bool:
    """Whether ``address`` may use a key carrying ``allowlist``.

    A NULL allowlist means the filter is off (the column's documented
    meaning). An empty list means the same: ``service.create_api_key``
    normalises ``[]`` to NULL so the shape should not exist, and reading a
    stray one as "deny everything" would lock a merchant out of their own
    account over a data artefact.

    Entries may be single addresses (``198.51.100.7``) or CIDR blocks
    (``203.0.113.0/24``), IPv4 or IPv6; a host address with a prefix is read
    as its network (``strict=False``). An entry that does not parse is
    skipped rather than fatal — one bad row must not disable the whole
    filter — and an unparseable client address (``UNKNOWN_IP``, i.e. no peer
    at all) never matches.

    Args:
        allowlist: The key's ``ip_allowlist`` column, as stored.
        address: The caller's address from ``core.client_ip``.

    Returns:
        Whether the request may proceed.
    """
    if not allowlist:
        return True
    try:
        caller = ipaddress.ip_address(address)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:  # only reachable via a hand-edited row; the schema rejects these
            continue
        if caller in network:
            return True
    return False


async def _touch_last_used(db: AsyncSession, key: MerchantApiKey) -> None:
    """Stamp ``last_used_at``. Best effort — never fails the request.

    Throttled by ``_LAST_USED_MIN_INTERVAL`` on both sides: in Python, so the
    common request issues no statement at all, and again in the UPDATE's
    WHERE clause, so two racing requests cannot both take the row lock. The
    write rides the request's own transaction, so a request that later rolls
    back loses the stamp — acceptable for a field nothing decides on.

    Args:
        db: The request session.
        key: The authenticated key row.
    """
    stamp = now()
    if key.last_used_at is not None and stamp - key.last_used_at < _LAST_USED_MIN_INTERVAL:
        return
    # A failure here means the database is already in trouble and the request
    # will surface that on its own next statement; this helper simply refuses
    # to be the thing that raises.
    with contextlib.suppress(Exception):
        await db.execute(
            update(MerchantApiKey)
            .where(
                MerchantApiKey.id == key.id,
                (MerchantApiKey.last_used_at.is_(None))
                | (MerchantApiKey.last_used_at < stamp - _LAST_USED_MIN_INTERVAL),
            )
            .values(last_used_at=stamp)
        )


def _fresh_timestamp(raw: str) -> None:
    """Raise unless ``raw`` is a unix-seconds value inside the tolerance window.

    Args:
        raw: The ``X-Merchant-Timestamp`` header, as sent.

    Raises:
        UnauthorizedError: If it is not an integer, or is outside ±300 s.
    """
    try:
        sent = int(raw)
    except ValueError:
        raise UnauthorizedError(
            f"{TIMESTAMP_HEADER} must be unix seconds", code=CODE_STALE_TIMESTAMP
        ) from None
    if abs(int(now().timestamp()) - sent) > TIMESTAMP_TOLERANCE_SECONDS:
        raise UnauthorizedError(
            f"{TIMESTAMP_HEADER} is outside the ±{TIMESTAMP_TOLERANCE_SECONDS}s window; "
            "check the clock on the calling server",
            code=CODE_STALE_TIMESTAMP,
        )


async def merchant_auth(
    request: Request, db: Annotated[AsyncSession, Depends(db_session)]
) -> Merchant:
    """Authenticate a signed ``/merchant/v1`` request and return the merchant.

    See the module docstring for the order of the checks and why. Nothing
    here logs the secret, the signing key or the signature: the structured
    logger redacts ``secret`` / ``signature`` / ``key`` by name anyway
    (``core.logging.REDACTED_KEYS``), and this path writes no log line of its
    own to begin with.

    Args:
        request: The incoming request — headers, raw body, and client address.
        db: The request session, shared with the endpoint behind this
            dependency (which is why it is ``api.v1.deps.db_session`` and not
            a session of our own).

    Returns:
        The authenticated, non-frozen merchant — a row loaded from Postgres,
        so ``merchant.id`` is always a real UUID. That matters downstream:
        ``orders.service.Actor`` accepts ``merchant_id=""`` (``"" is not
        None``) and an empty string reaches Postgres as ``uuid = ''``, i.e. a
        ``DataError`` and a 500 where a clean 401 belonged. This dependency
        is the boundary that keeps such a value from existing at all.

    Raises:
        RateLimitedError: 429, either axis.
        UnauthorizedError: 401 — headers missing, timestamp outside the
            window, or the credential did not verify.
        ForbiddenError: 403 — the merchant is frozen, or the caller's address
            is not on this key's allowlist.
    """
    settings = get_settings()
    await guard_ip(request, bucket=RATE_BUCKET)

    key_id = request.headers.get(KEY_HEADER, "")
    timestamp = request.headers.get(TIMESTAMP_HEADER, "")
    provided = request.headers.get(SIGNATURE_HEADER, "")
    if not key_id or not timestamp or not provided:
        raise UnauthorizedError(
            f"{KEY_HEADER}, {TIMESTAMP_HEADER} and {SIGNATURE_HEADER} are all required",
            code=CODE_MISSING_CREDENTIALS,
        )
    _fresh_timestamp(timestamp)

    # Starlette caches the body on the request, so reading it here does not
    # consume it — the endpoint behind this dependency still parses its own.
    message = signing.canonical_message(
        timestamp=timestamp,
        method=request.method,
        path=request.url.path,
        body=await request.body(),
    )
    row = (
        await db.execute(
            select(MerchantApiKey, Merchant)
            .join(Merchant, Merchant.id == MerchantApiKey.merchant_id)
            .where(MerchantApiKey.key_id == key_id)
        )
    ).one_or_none()
    key: MerchantApiKey | None = None
    merchant: Merchant | None = None
    if row is not None:
        key, merchant = row
    usable = key is not None and key.revoked_at is None
    signing_key = key.secret_hash if (key is not None and usable) else _DUMMY_SIGNING_KEY
    # Always computed, always compared — see "Timing shape" in the module docstring.
    signature_ok = signing.signature_matches(signing_key, message, provided)
    if key is None or merchant is None or not usable or not signature_ok:
        raise UnauthorizedError(_INVALID_DETAIL, code=CODE_INVALID_CREDENTIALS)

    over_key = await hit_counter(
        _RATE_KEY.format(key_id=key.key_id),
        limit=settings.merchant_api_key_rate_max,
        window=settings.auth_ip_guard_window_seconds,
    )
    if over_key:
        raise RateLimitedError("too many requests for this API key, slow down")

    if merchant.status == "frozen":
        raise ForbiddenError(
            "merchant account is frozen; contact support", code=CODE_MERCHANT_FROZEN
        )
    if not address_allowed(key.ip_allowlist, client_ip(request)):
        raise ForbiddenError(
            "this API key does not allow requests from that address",
            code=CODE_IP_NOT_ALLOWED,
        )

    await _touch_last_used(db, key)
    return merchant


__all__ = [
    "CODE_INVALID_CREDENTIALS",
    "CODE_IP_NOT_ALLOWED",
    "CODE_MERCHANT_FROZEN",
    "CODE_MISSING_CREDENTIALS",
    "CODE_STALE_TIMESTAMP",
    "KEY_HEADER",
    "RATE_BUCKET",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "TIMESTAMP_TOLERANCE_SECONDS",
    "address_allowed",
    "merchant_auth",
]
