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

**Byte-body endpoints only.** The dependency reads ``await request.body()``,
which Starlette caches on the request so the endpoint behind it still parses
its own JSON. That cache is only populated on the body branch: an endpoint
declaring ``Form(...)`` or ``UploadFile`` makes FastAPI take
``request.form()`` instead, which consumes the stream without setting
``_body`` — and then this dependency raises ``RuntimeError("Stream
consumed")`` on every call. ``/merchant/v1`` is a JSON API and must stay one;
a form endpoint would need the body read hoisted into middleware.

## The order of checks, and why

1. **IP axis of the rate guard**, before anything is parsed — an unauthenticated
   flood must cost us one Redis INCR, not a database round-trip.
2. **Headers present**, **timestamp strictly numeric and fresh**. These get
   their own error codes: a clock 400 seconds out is the single most common
   integration bug and telling the merchant so leaks nothing about any
   credential.
3. **The credential itself** — unknown key, revoked key and bad signature are
   one indistinguishable 401 (spec §9.2).
4. **Merchant axis of the rate guard**, charged on the key only once the
   signature has verified. See ``settings.merchant_api_key_rate_max``.
5. **Frozen merchant** → 403 ``merchant_frozen``; **IP allowlist** → 403
   ``ip_not_allowed``. Both are authenticated failures, so they are counted.
6. ``last_used_at``, best effort and throttled.

## Replay, and why nothing here single-uses a signature

A signature is valid for the ±300 s window and **may be presented more than
once**. That is deliberate, and it was briefly the other way: a ``SET NX``
marker made each signature single-use, which was reverted because **a
replaying attacker and a retrying client send byte-identical requests** — no
marker can tell them apart. Single-use therefore does not buy replay
protection so much as it breaks at-least-once retries, on the money path: an
HTTP client that resends after a reset connection gets an auth error for a
network fault, and if the first attempt already created an order the caller
never learns it exists. Our own edge makes that likelier than average, since
deploys are stop-then-start (the Caddyfile's ``lb_try_duration`` comment
exists because that gap used to produce 502s).

Neither AWS SigV4 nor Stripe single-uses a signature either, for the same
reason. The posture we actually rely on is three-layered and each layer is
someone's job:

- **The ±300 s window** bounds how long a captured request stays usable — this
  module.
- **Credentials stay out of logs.** Caddy redacts only ``Authorization``, so
  both ``X-Merchant-Key`` and ``X-Merchant-Signature`` were being written to
  stdout and shipped to Loki verbatim; ``infra/caddy/Caddyfile.prod`` now
  deletes them from the access log. That was the capture vector the single-use
  marker was reaching for, closed where it actually lives.
- **Idempotency makes a repeat harmless** for mutations. Order creation is
  idempotent on ``merchant_order_id`` (spec §9.3) — Task 4's job, and now the
  only thing standing between a replayed mutation and a duplicate order.

A replay inside the window by someone who can observe traffic is **accepted**.

## Timing shape

An early ``return`` on "no such key" would skip the HMAC entirely, so the
unknown- and revoked-key paths sign against ``_DUMMY_SECRET`` and compare
anyway — the same shape ``auth.service.password_login`` uses for absent
accounts. The claim that buys is narrow and worth stating exactly: **the
response payload is identical for all three failures and the HMAC cost is
equalised.** It is not a constant-time path end to end: an unknown ``key_id``
is an index miss while a known one is a hit plus a join, and only the known
one runs a decrypt. One Postgres round-trip dwarfs both a 32-byte HMAC and a
48-byte SecretBox open, so the residual signal sits far below the noise of a
network round-trip. Equalising the crypto is what is cheap and available;
equalising the database is not.

## Inherited assumption: the caller's address

``ip_allowlist`` is enforced against ``core.client_ip``, which takes the first
``X-Forwarded-For`` entry with **no trusted-proxy check** — its safety rests
entirely on the shared edge overwriting that header rather than appending to
it (``infra/edge/Caddyfile``, and that helper's own docstring). That
assumption previously only decided which rate-limit counter got charged; here
it decides whether an allowlist can be bypassed with one header. It is
deliberately still used rather than a bespoke read: one home for the answer
beats three that can drift. Hardening ``client_ip`` itself with a
trusted-proxy check is filed for M3 — repo-wide, and the mitigating fact is
that the allowlist is defence-in-depth **on top of** the HMAC, never the
primary control: an attacker who can spoof the header still has no secret.
"""

from __future__ import annotations

import contextlib
import ipaddress
import re
from datetime import timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, Request
from nacl.exceptions import CryptoError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core import crypto
from yupay.core.client_ip import client_ip
from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.errors import ForbiddenError, RateLimitedError, UnauthorizedError
from yupay.core.logging import get_logger
from yupay.modules.auth.ip_guard import guard_ip, hit_counter
from yupay.modules.merchants import signing
from yupay.modules.merchants.models import Merchant, MerchantApiKey

log = get_logger("yupay.merchants.auth")

#: The three request headers. Documented in the module README, which is what
#: third parties implement against — renaming one is a breaking change to a
#: contract nobody but its owner can redeploy.
KEY_HEADER = "X-Merchant-Key"
TIMESTAMP_HEADER = "X-Merchant-Timestamp"
SIGNATURE_HEADER = "X-Merchant-Signature"

#: How far a request timestamp may sit from ours, either way (spec §9.2).
TIMESTAMP_TOLERANCE_SECONDS = 300

#: The ``auth_ip_guard_bucket_max`` bucket charged for the IP axis.
RATE_BUCKET = "merchant-api"

#: Redis key for the merchant axis. Catalogued in
#: ``docs/architecture/cache-keys.md``.
_RATE_KEY = "merchants:apikey:{key_id}"

#: Unix seconds, strictly. ``int()`` would also accept ``"1_725_000_000"``,
#: ``" 1725 "``, ``"+1725"`` and Arabic-Indic digits — harmless (the raw
#: header is what gets signed, so no two readings can disagree) but the
#: README says "unix seconds" and clients would quietly diverge.
_UNIX_SECONDS = re.compile(r"\A[0-9]{1,20}\Z")

#: Characters a request-line field may carry through unencoded. Only reached
#: on the non-ASCII fallback in :func:`_request_line_field`.
_RAW_SAFE = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ "

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

#: Signed against when there is no usable key, so the HMAC is computed and
#: compared whether or not the key id exists. A constant, not a credential.
_DUMMY_SECRET = "ypms_merchant-auth-timing-parity"  # noqa: S105  # not a credential

#: Do not rewrite ``last_used_at`` more often than this. Without the guard
#: every request UPDATEs one row, and concurrent requests on the same key
#: then serialise on its row lock for the length of the whole transaction —
#: a throughput cliff on the one surface built for throughput. The column
#: answers "is this key still in use", which one write a minute answers just
#: as well.
_LAST_USED_MIN_INTERVAL = timedelta(seconds=60)


def _request_line_field(raw: bytes) -> str:
    """Decode one request-line field (path or query) for signing.

    The fast path — every real request — is a plain ASCII decode: an HTTP
    request line is ASCII by construction, and percent-encoded, so the value
    can contain no literal LF and cannot forge a field boundary in the
    canonical string.

    The fallback covers a server that hands through raw non-ASCII bytes:
    those are percent-encoded rather than replaced, so distinct byte strings
    stay distinct. Two forms that collide here (a raw ``0xC3 0xA9`` and a
    literal ``%C3%A9``) percent-decode to the same routing path anyway, so
    the collision selects the same endpoint with the same parameters.

    Args:
        raw: The field's bytes from the ASGI scope.

    Returns:
        The text to place in the canonical string.
    """
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        return quote(raw, safe=_RAW_SAFE)


def request_target(request: Request) -> tuple[str, str]:
    """The signed ``(raw_path, raw_query)`` pair for a request.

    Reads ``scope["raw_path"]`` — the bytes as they arrived, before
    percent-decoding — and falls back to re-encoding ``scope["path"]`` when a
    server does not provide it (the ASGI spec makes ``raw_path`` optional;
    uvicorn and httpx's test transport both set it, query already stripped).

    Args:
        request: The incoming request.

    Returns:
        ``(raw_path, raw_query)``; the query is ``""`` when absent.
    """
    raw_path = request.scope.get("raw_path")
    path = (
        _request_line_field(raw_path)
        if isinstance(raw_path, bytes)
        else quote(request.scope.get("path", ""), safe="/")
    )
    return path, _request_line_field(request.scope.get("query_string", b""))


def address_allowed(allowlist: list[str] | None, address: str) -> bool:
    """Whether ``address`` may use a key carrying ``allowlist``.

    A NULL allowlist means the filter is off (the column's documented
    meaning). An empty list means the same: ``service.create_api_key``
    normalises ``[]`` to NULL and the schema rejects an empty array, so the
    shape is unreachable through the API — and reading a stray one as "deny
    everything" would lock a merchant out over a data artefact. The caller
    logs a warning when it sees one, because an operator who hand-edited a
    row to ``{}`` meaning "block this key" got the exact opposite.

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
    """Raise unless ``raw`` is unix seconds inside the tolerance window.

    Args:
        raw: The ``X-Merchant-Timestamp`` header, as sent.

    Raises:
        UnauthorizedError: If it is not strictly digits, or outside ±300 s.
    """
    if _UNIX_SECONDS.match(raw) is None:
        raise UnauthorizedError(
            f"{TIMESTAMP_HEADER} must be unix seconds (digits only)",
            code=CODE_STALE_TIMESTAMP,
        )
    if abs(int(now().timestamp()) - int(raw)) > TIMESTAMP_TOLERANCE_SECONDS:
        raise UnauthorizedError(
            f"{TIMESTAMP_HEADER} is outside the ±{TIMESTAMP_TOLERANCE_SECONDS}s window; "
            "check the clock on the calling server",
            code=CODE_STALE_TIMESTAMP,
        )


def _secret_of(key: MerchantApiKey | None) -> str:
    """The HMAC key to verify against — the row's secret, or a constant dummy.

    Args:
        key: The looked-up row, or ``None`` when the key id is unknown.

    Returns:
        The decrypted secret for a usable key; ``_DUMMY_SECRET`` when the key
        is unknown, revoked, or its ciphertext will not open — a wrong
        application key or a tampered row, both of which must read as "bad
        credentials", never as a 500.
    """
    if key is None or key.revoked_at is not None:
        return _DUMMY_SECRET
    try:
        return crypto.decrypt(
            key.secret_enc, key.secret_nonce, purpose=crypto.PURPOSE_MERCHANT_API_KEY
        )
    except CryptoError:
        # A wrong application key or a tampered row. Reads as bad credentials,
        # never as a 500 — and the warning is how an operator finds out that
        # every key minted under an older ``INVENTORY_ENC_KEY`` is now dead.
        log.warning("merchant_api_key_undecryptable", key_id=key.key_id)
        return _DUMMY_SECRET


async def merchant_auth(
    request: Request, db: Annotated[AsyncSession, Depends(db_session)]
) -> Merchant:
    """Authenticate a signed ``/merchant/v1`` request and return the merchant.

    See the module docstring for the order of the checks and why. Nothing
    here logs the secret or the signature: the structured logger redacts
    ``secret`` / ``signature`` / ``key`` by name
    (``core.logging.REDACTED_KEYS``), and this path writes no log line of its
    own on the happy path.

    Args:
        request: The incoming request — headers, raw body, request line, and
            client address.
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

    raw_path, raw_query = request_target(request)
    # Starlette caches the body on the request, so reading it here does not
    # consume it for a byte-body endpoint — see the module docstring for the
    # form-endpoint exception.
    message = signing.canonical_message(
        timestamp=timestamp,
        method=request.method,
        raw_path=raw_path,
        raw_query=raw_query,
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
    # Always computed, always compared — see "Timing shape" in the module docstring.
    signature_ok = signing.signature_matches(_secret_of(key), message, provided)
    if key is None or merchant is None or key.revoked_at is not None or not signature_ok:
        raise UnauthorizedError(_INVALID_DETAIL, code=CODE_INVALID_CREDENTIALS)

    over_key = await hit_counter(
        _RATE_KEY.format(key_id=key.key_id),
        limit=settings.merchant_api_key_rate_max,
        window=settings.auth_ip_guard_window_seconds,
    )
    if over_key:
        raise RateLimitedError(
            "too many requests for this API key, slow down",
            retry_after=settings.auth_ip_guard_window_seconds,
        )

    if merchant.status == "frozen":
        raise ForbiddenError(
            "merchant account is frozen; contact support", code=CODE_MERCHANT_FROZEN
        )
    if key.ip_allowlist is not None and not key.ip_allowlist:
        # An operator who hand-edited a row to ``{}`` to block a key got the
        # opposite. ``key_id`` is the public half — it travels in a plaintext
        # header on every request and is shown in the cabinet — so it is safe
        # to name here, and naming it is the only way to find the row.
        log.warning(
            "merchant_api_key_empty_allowlist",
            key_id=key.key_id,
            merchant_id=key.merchant_id,
            hint="an empty ip_allowlist means NO filter, same as NULL; "
            "delete the key or set addresses to restrict it",
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
    "request_target",
]
