"""Circuit breaker in front of an advisory supplier call.

The problem it exists for: the G2B client retries 429/5xx four times with a
1→2→4→8s backoff, so while the supplier is unwell a single player check sits
there for up to ~15s of sleeping plus the requests themselves. That is fine
for order fulfilment, which runs in the background and must keep trying, and
useless for a customer staring at a spinner — they would rather be told in
200ms that the check is unavailable.

Every method fails open. A breaker whose own storage is down must not become
the outage it was added to contain.
"""

from __future__ import annotations

import pytest
from yupay.modules.integrations.breaker import SupplierBreaker


class _FakeRedis:
    """Enough of the Redis surface for the breaker, plus a failure switch."""

    def __init__(self, *, broken: bool = False) -> None:
        self.store: dict[str, str] = {}
        self.broken = broken

    def _boom(self) -> None:
        if self.broken:
            raise ConnectionError("redis is down")

    async def exists(self, key: str) -> int:
        self._boom()
        return 1 if key in self.store else 0

    async def incr(self, key: str) -> int:
        self._boom()
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])

    async def expire(self, key: str, seconds: int) -> bool:
        self._boom()
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._boom()
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        self._boom()
        n = 0
        for k in keys:
            n += self.store.pop(k, None) is not None
        return n


@pytest.fixture
def redis(monkeypatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr("yupay.modules.integrations.breaker.get_redis", lambda: fake)
    return fake


def _breaker(**kw) -> SupplierBreaker:
    return SupplierBreaker("g2b:player_check", threshold=3, cooldown_seconds=30, **kw)


@pytest.mark.asyncio
async def test_starts_closed(redis) -> None:
    assert await _breaker().is_open() is False


@pytest.mark.asyncio
async def test_stays_closed_below_the_threshold(redis) -> None:
    b = _breaker()
    await b.record_failure()
    await b.record_failure()
    assert await b.is_open() is False


@pytest.mark.asyncio
async def test_opens_on_the_threshold_failure(redis) -> None:
    b = _breaker()
    for _ in range(3):
        await b.record_failure()
    assert await b.is_open() is True


@pytest.mark.asyncio
async def test_a_success_clears_the_run(redis) -> None:
    """Consecutive failures, not lifetime failures — otherwise a healthy
    supplier trips the breaker eventually just by being used enough."""
    b = _breaker()
    await b.record_failure()
    await b.record_failure()
    await b.record_success()
    await b.record_failure()
    assert await b.is_open() is False


@pytest.mark.asyncio
async def test_a_success_closes_an_open_breaker(redis) -> None:
    """The half-open probe that gets through after the cooldown must be able
    to end the outage, not merely avoid extending it."""
    b = _breaker()
    for _ in range(3):
        await b.record_failure()
    assert await b.is_open() is True
    await b.record_success()
    assert await b.is_open() is False


@pytest.mark.asyncio
async def test_two_breakers_do_not_share_a_circuit(redis) -> None:
    a = SupplierBreaker("g2b:player_check", threshold=2, cooldown_seconds=30)
    other = SupplierBreaker("waxpeer:player_check", threshold=2, cooldown_seconds=30)
    for _ in range(2):
        await a.record_failure()
    assert await a.is_open() is True
    assert await other.is_open() is False


@pytest.mark.asyncio
async def test_redis_down_reads_as_closed(monkeypatch) -> None:
    """Fail open: an unreachable Redis must not block every check."""
    monkeypatch.setattr(
        "yupay.modules.integrations.breaker.get_redis", lambda: _FakeRedis(broken=True)
    )
    b = _breaker()
    await b.record_failure()  # must not raise
    await b.record_success()  # must not raise
    assert await b.is_open() is False


@pytest.mark.asyncio
async def test_threshold_of_zero_disables_the_breaker(redis) -> None:
    """The documented kill switch: an operator who wants the old behaviour
    back sets the threshold to 0 rather than redeploying a revert."""
    b = SupplierBreaker("g2b:player_check", threshold=0, cooldown_seconds=30)
    for _ in range(5):
        await b.record_failure()
    assert await b.is_open() is False
