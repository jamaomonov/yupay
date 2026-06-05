"""Lightweight Redis per-IP rate guard for sensitive auth endpoints.

Not a substitute for full edge rate limiting — just blunts brute force and
email bombing on ``login`` / ``password/forgot``. Best-effort: Redis errors fail
open (the endpoint proceeds) so a cache hiccup never locks out auth.
"""

from __future__ import annotations

import contextlib

from fastapi import Request

from yupay.core.config import get_settings
from yupay.core.errors import RateLimitedError
from yupay.core.redis import get_redis


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def guard_ip(request: Request, *, bucket: str) -> None:
    """Increment a per-IP counter; raise ``RateLimitedError`` past the threshold."""
    settings = get_settings()
    ip = _client_ip(request)
    key = f"auth:ipguard:{bucket}:{ip}"
    redis = get_redis()
    count = 0
    with contextlib.suppress(Exception):  # fail open on Redis trouble
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, settings.auth_ip_guard_window_seconds)
    if count > settings.auth_ip_guard_max:
        raise RateLimitedError("too many attempts, slow down")
