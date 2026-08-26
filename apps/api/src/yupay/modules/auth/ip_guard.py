"""Lightweight Redis per-IP rate guard for sensitive auth endpoints.

Not a substitute for full edge rate limiting — just blunts brute force and
email bombing on ``login`` / ``password/forgot``. Best-effort: Redis errors fail
open (the endpoint proceeds) so a cache hiccup never locks out auth.

Buckets do not have to share a threshold. They did, and the shared value is
written for brute force, which made it wrong for the one bucket that is not a
credential endpoint: the storefront player check. A customer runs that while
filling in the order form, and Uzbek mobile carriers put many subscribers
behind a single address — so ten a minute is spent collectively by strangers,
and the loser sees "couldn't check" on a perfectly good id. Raising the shared
value instead would have loosened `login` in the same stroke.
"""

from __future__ import annotations

import contextlib

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


async def guard_ip(request: Request, *, bucket: str) -> None:
    """Increment a per-IP counter; raise ``RateLimitedError`` past the threshold."""
    settings = get_settings()
    ip = client_ip(request)
    key = f"auth:ipguard:{bucket}:{ip}"
    redis = get_redis()
    count = 0
    with contextlib.suppress(Exception):  # fail open on Redis trouble
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, settings.auth_ip_guard_window_seconds)
    if count > bucket_limit(settings, bucket):
        raise RateLimitedError("too many attempts, slow down")
