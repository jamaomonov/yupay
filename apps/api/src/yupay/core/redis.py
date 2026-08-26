"""Async Redis client singleton.

Timeouts are deliberate and short. Everything guarding the request path — the
ip guard, the supplier circuit breaker, every cache read — is written to fail
open, so a Redis *error* degrades to "no throttling, no cache" and the request
proceeds. That is the right posture, but it only covers an error: with no
socket timeout a wedged Redis stalls each of those awaits indefinitely, on the
single event loop the whole API shares, and the fail-open branch never runs.
A bounded timeout is what turns a hang back into an error it can handle.
"""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from yupay.core.config import get_settings

_client: Redis | None = None


def get_redis() -> Redis:
    """Return the lazily-initialised async Redis client."""
    global _client
    if _client is None:
        _client = from_url(
            get_settings().redis_url,
            encoding="utf-8",
            decode_responses=True,
            # Redis is local to the box; half a second is already an eternity
            # for it, and anything longer is time the event loop spends serving
            # nobody.
            socket_timeout=0.5,
            socket_connect_timeout=0.5,
            # Notice a connection that died quietly instead of handing it out
            # and failing on first use, which reads as an outage rather than
            # the reconnect it should have been.
            health_check_interval=30,
        )
    return _client


async def close_redis() -> None:
    """Close the Redis client on shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
