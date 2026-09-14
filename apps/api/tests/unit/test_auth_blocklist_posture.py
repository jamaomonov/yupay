"""What the revocation blocklist does when Redis cannot answer.

This read runs on **every authenticated request**, so its failure mode is not
a detail. It had three options and was taking the worst one: raise, which both
blocked the customer and paged us. Sentry surfaced it through the WebSocket
handshake (`realtime.routes.handshake`), but the blast radius was every
authenticated endpoint in the API.

The posture is now fail-open, and these tests are where that decision is
pinned rather than left to be rediscovered from a traceback. Its cost is
bounded by ADR-0007's own design: the blocklist accelerates an expiry that
happens anyway inside the 15-minute access TTL.
"""

from __future__ import annotations

import pytest
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError
from yupay.modules.auth import service as svc


class _Redis:
    """Stand-in for the client, answering however the test needs."""

    def __init__(self, *, answer: str | None = None, raises: Exception | None = None) -> None:
        self._answer = answer
        self._raises = raises

    async def get(self, _key: str) -> str | None:
        if self._raises is not None:
            raise self._raises
        return self._answer


@pytest.mark.parametrize(
    "boom",
    [RedisTimeoutError("Timeout reading from redis:6379"), RedisError("connection reset")],
)
async def test_an_unreadable_blocklist_does_not_refuse_the_request(
    monkeypatch: pytest.MonkeyPatch, boom: Exception
) -> None:
    """Neither 500 nor 401.

    Refusing would sign every customer out at once for the length of a Redis
    blip — a cache outage promoted to a total one. Raising did that *and*
    paged. Allowing costs a revoked token the seconds of the blip, never past
    the TTL it was already going to die of.
    """
    monkeypatch.setattr(svc, "get_redis", lambda: _Redis(raises=boom))

    assert await svc._is_blocklisted("auth:revoked:whatever", kind="access") is False


async def test_a_readable_blocklist_still_revokes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-open must not become always-open — the control still works."""
    monkeypatch.setattr(svc, "get_redis", lambda: _Redis(answer="1"))

    assert await svc._is_blocklisted("auth:revoked:whatever", kind="access") is True


async def test_an_absent_key_is_not_a_revocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "get_redis", lambda: _Redis(answer=None))

    assert await svc._is_blocklisted("auth:revoked:whatever", kind="access") is False


async def test_the_key_is_never_logged(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """A `jti`/`sid` identifies a live session; only the blocklist's name goes out."""
    secret_key = "auth:revoked:01a0-secret-jti"
    monkeypatch.setattr(svc, "get_redis", lambda: _Redis(raises=RedisError("down")))

    with caplog.at_level("ERROR"):
        await svc._is_blocklisted(secret_key, kind="access")

    assert "01a0-secret-jti" not in caplog.text
