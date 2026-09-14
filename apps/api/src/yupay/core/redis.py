"""Async Redis client singleton.

Timeouts are deliberate and short. Everything guarding the request path — the
ip guard, the supplier circuit breaker, every cache read — is written to fail
open, so a Redis *error* degrades to "no throttling, no cache" and the request
proceeds. That is the right posture, but it only covers an error: with no
socket timeout a wedged Redis stalls each of those awaits indefinitely, on the
single event loop the whole API shares, and the fail-open branch never runs.
A bounded timeout is what turns a hang back into an error it can handle.

That claim was audited on 2026-09-14 against Sentry and was true of the ip
guard and the breaker (both `contextlib.suppress`) and false of the two paths
actually paging us: the FX rate cache, whose failure now reads as
`FxUnavailableError` rather than a 500, and `auth.current_user`'s revocation
blocklist. A sentence like the one above is worth re-reading against production
occasionally; it describes an intention, and intentions do not propagate to new
call sites on their own.
"""

from __future__ import annotations

from redis.asyncio import Redis, from_url
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

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
            # ...and then actually reconnect. The health check above only
            # *detects* the dead socket: it PINGs, the PING reads nothing, and
            # without a retry that read times out into the caller's lap. The
            # library defaults to zero retries, so every silently-dropped idle
            # connection surfaced as a 500 on whatever request happened to pick
            # it out of the pool. How long that had been true is unknown — it
            # became visible only when Sentry was wired up, which then caught
            # 138 of them in five days, on a Redis measured at 2 MB used, 0
            # blocked clients and 0 ops/sec. A busy Redis was never the problem;
            # an unused one was, because idle is exactly how a connection dies
            # unnoticed.
            #
            # One retry, because the failure being answered is "this particular
            # socket is gone" and the second attempt gets a fresh one. It is not
            # a strategy for waiting out an outage: that doubles the worst case
            # to ~1s and is meant to.
            retry=Retry(ExponentialBackoff(cap=0.05, base=0.01), retries=1),
            retry_on_error=[RedisConnectionError, RedisTimeoutError],
        )
    return _client


async def close_redis() -> None:
    """Close the Redis client on shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
