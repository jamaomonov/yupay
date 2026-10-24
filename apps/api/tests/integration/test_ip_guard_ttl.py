"""``ip_guard.hit_counter`` never leaves a counter without a TTL.

Regression, 2026-10-24: a reseller's whole API was answered 429 for hours. The IP counter
for ``merchant-api`` sat at 2148 with ``TTL -1`` — the INCR of a window's first hit had
landed, the separate EXPIRE had not, and nothing ever set one again, so the window never
ended. The counter must carry a TTL after every hit, and a key already stuck without one
must heal on its next hit instead of blocking forever.
"""

from __future__ import annotations

import pytest
from yupay.core.redis import get_redis
from yupay.modules.auth.ip_guard import hit_counter

pytestmark = pytest.mark.asyncio


async def test_every_hit_leaves_a_ttl() -> None:
    redis = get_redis()
    key = "auth:ipguard:test-ttl:203.0.113.7"
    await redis.delete(key)

    assert await hit_counter(key, limit=5, window=60) is False
    assert 0 < await redis.ttl(key) <= 60
    await hit_counter(key, limit=5, window=60)
    assert 0 < await redis.ttl(key) <= 60


async def test_a_counter_stuck_without_ttl_heals_on_the_next_hit() -> None:
    redis = get_redis()
    key = "auth:ipguard:test-stuck:203.0.113.8"
    await redis.set(key, 2148)  # what prod held: over the limit, no TTL
    assert await redis.ttl(key) == -1

    await hit_counter(key, limit=600, window=60)

    assert 0 < await redis.ttl(key) <= 60
