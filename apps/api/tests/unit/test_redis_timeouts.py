"""The Redis client must give up quickly, not hang.

Everything guarding the request path — the ip guard, the supplier circuit
breaker, every cache read — is written to "fail open": an exception means the
request proceeds unthrottled rather than everyone being locked out. That covers
an *error*. It does not cover a *hang*: with no socket timeout a wedged Redis
stalls each of those calls indefinitely, on the one event loop the whole API
shares, and failing open never gets a chance to happen.

This box has a documented history of a disk fill wedging a colocated service,
so a slow Redis is a realistic incident rather than a theoretical one.

What actually happened was smaller and stranger than a wedge: a Redis holding
2 MB, serving 0 ops/sec, with nothing in its slow log but the Prometheus
exporter. Connections that sit idle die quietly, and the client was configured
to *notice* that (a health-check PING) without being allowed to do anything
about it (zero retries), so the PING's own read timed out into the caller.
Hence the retry test below — the health check and the retry are one mechanism,
and either alone is a false comfort.
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


def test_a_dead_connection_is_retried_rather_than_surfaced() -> None:
    """The other half of the health check.

    Detecting a dead socket and then handing its timeout to the caller is not
    a recovery: on production it read as 138 unhandled `TimeoutError`s in five
    days, on a Redis that was doing nothing at all. One retry gets a fresh
    connection; more than that would be waiting out an outage on the request
    path, which the socket timeouts above exist to refuse.
    """
    # Read off ``connection_kwargs`` like every other test here, rather than
    # building a connection: ``make_connection`` is untyped in redis-py's
    # stubs, and ``mypy apps`` — which CI runs over the tests too — refuses an
    # untyped call in a typed context.
    kwargs = rmod.get_redis().connection_pool.connection_kwargs
    retry = kwargs.get("retry")
    assert retry is not None
    assert getattr(retry, "_retries", 0) >= 1, "a dead socket must be retried, not raised"
    retried_on = {exc.__name__ for exc in kwargs.get("retry_on_error", [])}
    assert {"TimeoutError", "ConnectionError"} <= retried_on


def test_decode_and_encoding_are_unchanged() -> None:
    """Guard the edit itself: every caller reads strings back, so flipping
    decode_responses would break them all at once."""
    kwargs = rmod.get_redis().connection_pool.connection_kwargs
    assert kwargs.get("decode_responses") is True
    assert kwargs.get("encoding") == "utf-8"
