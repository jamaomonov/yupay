"""A circuit breaker for advisory supplier calls.

The G2B client retries 429/5xx four times with a 1→2→4→8s backoff, which is
right for order fulfilment — that runs in the background, the money is already
taken, and giving up early only pushes the order into the manual queue. It is
wrong for the storefront player check: that is an optional lookup with a
customer watching a spinner, and while the supplier is unwell every one of
them pays ~15s of sleeping to arrive at the same "couldn't check" they could
have had immediately.

So the breaker guards the *advisory* path only. Nothing here is wired into
fulfilment, deliberately — see ADR-0059.

State lives in Redis rather than in the process, because the deployment is
meant to stay horizontally splittable: with the state in memory, a second API
worker would learn about an outage separately, and each would spend its own
run of customers discovering it.

Every operation fails open. A breaker whose own storage is down must not
become the outage it was added to contain, so a Redis error reads as "closed"
and the call proceeds exactly as it did before this module existed.
"""

from __future__ import annotations

import contextlib

from yupay.core.logging import get_logger
from yupay.core.redis import get_redis

logger = get_logger("yupay.integrations.breaker")

#: How long a run of failures is remembered. Comfortably longer than the
#: backoff of a single call, so failures from one bad spell accumulate
#: instead of ageing out between two slow retries.
_FAILURE_WINDOW_SECONDS = 120


class SupplierBreaker:
    """Trips after ``threshold`` consecutive failures, stays open for
    ``cooldown_seconds``, then lets the next call through as a probe.

    Args:
        name: Circuit identity, e.g. ``"g2b:player_check"``. Distinct names do
            not share a circuit, so one supplier's outage cannot silence
            another's checks.
        threshold: Consecutive failures that open the circuit. ``0`` disables
            the breaker entirely — the kill switch for an operator who wants
            the previous behaviour back without a redeploy.
        cooldown_seconds: How long the circuit stays open. Expiry *is* the
            half-open probe: the key simply goes away and the next call runs
            for real, either closing the circuit or re-opening it.
    """

    def __init__(self, name: str, *, threshold: int, cooldown_seconds: int) -> None:
        self._name = name
        self._threshold = threshold
        self._cooldown = cooldown_seconds

    @property
    def _open_key(self) -> str:
        return f"breaker:{self._name}:open"

    @property
    def _fail_key(self) -> str:
        return f"breaker:{self._name}:fails"

    async def is_open(self) -> bool:
        """Whether the call should be skipped. False on any Redis trouble."""
        if self._threshold <= 0:
            return False
        try:
            return bool(await get_redis().exists(self._open_key))
        except Exception:  # noqa: BLE001 — fail open, never block on the guard
            return False

    async def record_failure(self) -> None:
        """Count one failure; open the circuit once the run reaches the
        threshold. The counter carries its own TTL so an isolated failure a
        day later does not join a run from this morning."""
        if self._threshold <= 0:
            return
        with contextlib.suppress(Exception):  # best effort — never block on the guard
            redis = get_redis()
            count = await redis.incr(self._fail_key)
            if count == 1:
                await redis.expire(self._fail_key, _FAILURE_WINDOW_SECONDS)
            if count >= self._threshold:
                await redis.set(self._open_key, "1", ex=self._cooldown)
                logger.warning(
                    "breaker_open",
                    circuit=self._name,
                    failures=count,
                    cooldown_seconds=self._cooldown,
                )

    async def record_success(self) -> None:
        """Clear the run and close the circuit.

        Closing on success matters as much as clearing the run: the probe that
        gets through after a cooldown has to be able to *end* the outage, not
        just decline to extend it.
        """
        if self._threshold <= 0:
            return
        with contextlib.suppress(Exception):  # best effort — never block on the guard
            redis = get_redis()
            deleted = await redis.delete(self._fail_key, self._open_key)
            if deleted:
                logger.info("breaker_closed", circuit=self._name)
