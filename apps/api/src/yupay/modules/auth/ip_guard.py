"""Lightweight Redis per-IP rate guard for sensitive auth endpoints.

Not a substitute for full edge rate limiting — just blunts brute force and
email bombing on ``login`` / ``password/forgot``. Best-effort: Redis errors fail
open (the endpoint proceeds) so a cache hiccup never locks out auth.

Buckets do not have to share a threshold. They did, and the shared value is
written for brute force, which made it wrong for the one bucket that is not a
credential endpoint: the storefront player check. A customer runs that while
filling in the order form, and Uzbek mobile carriers put many subscribers
behind a single address — so ten a minute is spent collectively by strangers,
and the loser sees "couldn't check" on a perfectly good id.

The same carrier NAT is why credential endpoints throttle on two axes rather
than one. A single per-IP number cannot serve both purposes: low enough to stop
someone guessing one account's password, it locks out a whole carrier; high
enough for the carrier, it stops blunting brute force. So the IP bucket is
sized for a crowd, and a second, tight bucket counts attempts against one
*identity* — ``(ip, email)``. Between them:

* many guesses at one account  -> the subject bucket trips first;
* one guess at many accounts (credential stuffing, which the subject bucket
  cannot see) -> the IP bucket still catches it;
* six neighbours signing in behind one address -> neither trips.
"""

from __future__ import annotations

import contextlib
import hashlib

from fastapi import Request

from yupay.core.client_ip import client_ip
from yupay.core.config import Settings, get_settings
from yupay.core.errors import RateLimitedError
from yupay.core.redis import get_redis


def bucket_limit(settings: Settings, bucket: str) -> int:
    """The per-window ceiling for ``bucket``.

    Falls back to ``auth_ip_guard_max`` when the bucket is unlisted, and also
    when the override is <= 0 — a zero would read as "allow nothing" and a
    negative, past the ``count > limit`` comparison below, as "allow
    everything". Neither is a limit anybody meant to configure, so a typo
    lands on the safe default rather than silently removing the guard.
    """
    override = settings.auth_ip_guard_bucket_max.get(bucket)
    if override is not None and override > 0:
        return override
    return settings.auth_ip_guard_max


def subject_key(bucket: str, ip: str, subject: str) -> str:
    """Redis key for the per-identity counter.

    ``subject`` is hashed, never stored raw: an email in a Redis key is PII in
    plaintext to anything running ``MONITOR`` or ``SCAN`` (§9). The IP is part
    of the key too, so one attacker cannot lock a victim out of their own
    account from somewhere else — the limit follows the pair, not the person.
    """
    digest = hashlib.sha256(subject.strip().lower().encode()).hexdigest()[:32]
    return f"auth:ipguard:{bucket}:{ip}:s:{digest}"


async def hit_counter(key: str, *, limit: int, window: int) -> bool:
    """Count one attempt against ``key``. True when it puts the caller over ``limit``.

    The single fixed-window counter behind every guard in the app: INCR, set
    the TTL on the first hit of a window, compare. Public because the machine
    API's per-key axis (``merchants.auth``) needs the same counter on a key
    this module has no business knowing about — and a second copy of the
    INCR/EXPIRE dance is exactly how two guards drift into behaving
    differently under Redis trouble.

    Best-effort by design: a Redis error counts as "under the limit" so a
    cache hiccup degrades to no throttling rather than locking everyone out.
    Callers own the response — this returns a verdict and raises nothing.

    Args:
        key: The Redis key to charge. Callers namespace it themselves; every
            key is catalogued in ``docs/architecture/cache-keys.md``.
        limit: Hits allowed per window before this returns True.
        window: Window length in seconds, applied as the key's TTL.

    Returns:
        Whether this hit went over ``limit``.
    """
    count = 0
    with contextlib.suppress(Exception):  # fail open on Redis trouble
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window)
    return count > limit


async def guard_ip(request: Request, *, bucket: str, subject: str | None = None) -> None:
    """Throttle this attempt; raise ``RateLimitedError`` past a threshold.

    Args:
        request: the incoming request, for the real client address.
        bucket: which counter to charge, e.g. ``"login"``.
        subject: the identity being attempted — an email for the credential
            endpoints. When given, a second and much tighter counter is charged
            for ``(ip, subject)``, which is what keeps brute-force protection
            meaningful on an address a whole carrier shares. Omit it for
            buckets that guard a resource rather than a secret.
    """
    settings = get_settings()
    ip = client_ip(request)
    window = settings.auth_ip_guard_window_seconds

    # Charge both counters before deciding, so an attempt is never counted
    # against one axis and not the other depending on which trips first.
    over_ip = await hit_counter(
        f"auth:ipguard:{bucket}:{ip}", limit=bucket_limit(settings, bucket), window=window
    )
    over_subject = False
    if subject:
        over_subject = await hit_counter(
            subject_key(bucket, ip, subject),
            limit=settings.auth_ip_guard_subject_max,
            window=window,
        )

    if over_ip or over_subject:
        raise RateLimitedError("too many attempts, slow down")
