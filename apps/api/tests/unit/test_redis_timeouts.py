"""The Redis client must give up quickly, not hang.

Everything guarding the request path — the ip guard, the supplier circuit
breaker, every cache read — is written to "fail open": an exception means the
request proceeds unthrottled rather than everyone being locked out. That covers
an *error*. It does not cover a *hang*: with no socket timeout a wedged Redis
stalls each of those calls indefinitely, on the one event loop the whole API
shares, and failing open never gets a chance to happen.

This box has a documented history of a disk fill wedging a colocated service,
so a slow Redis is a realistic incident rather than a theoretical one.
"""

from __future__ import annotations

import pytest
from yupay.core import redis as rmod


@pytest.fixture(autouse=True)
async def _fresh_client():
    await rmod.close_redis()
    yield
    await rmod.close_redis()


def test_the_client_has_bounded_socket_timeouts() -> None:
    kwargs = rmod.get_redis().connection_pool.connection_kwargs
    for name in ("socket_timeout", "socket_connect_timeout"):
        value = kwargs.get(name)
        assert value is not None, f"{name} is unset — a wedged Redis would hang the event loop"
        assert 0 < value <= 2, f"{name}={value} is too long for a request-path guard"


def test_dead_connections_are_noticed_rather_than_reused() -> None:
    """Without a health check a pooled connection that died quietly is handed
    out again and fails on first use — which reads as a Redis outage rather
    than as the reconnect it should have been."""
    kwargs = rmod.get_redis().connection_pool.connection_kwargs
    assert kwargs.get("health_check_interval", 0) > 0


def test_decode_and_encoding_are_unchanged() -> None:
    """Guard the edit itself: every caller reads strings back, so flipping
    decode_responses would break them all at once."""
    kwargs = rmod.get_redis().connection_pool.connection_kwargs
    assert kwargs.get("decode_responses") is True
    assert kwargs.get("encoding") == "utf-8"
