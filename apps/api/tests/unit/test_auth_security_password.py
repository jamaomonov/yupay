"""argon2id password hashing: correctness, and that it stays off the event loop."""

from __future__ import annotations

import asyncio

import pytest
from yupay.modules.auth.security import hash_password, verify_password


async def test_hash_is_argon2id_and_verifies() -> None:
    h = await hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert await verify_password("correct horse battery staple", h) is True


async def test_verify_rejects_wrong_password() -> None:
    h = await hash_password("s3cret-pass")
    assert await verify_password("nope", h) is False


async def test_hashes_are_salted_and_unique() -> None:
    assert await hash_password("same") != await hash_password("same")


async def test_verify_handles_garbage_hash() -> None:
    assert await verify_password("x", "not-a-hash") is False


@pytest.mark.parametrize("call", ["hash", "verify"])
async def test_the_event_loop_keeps_running_during_the_hash(call: str) -> None:
    """The reason these are async at all.

    argon2 is deliberately expensive — measured at 98ms per verification on the
    production box, with `memory_cost` at 64 MiB. The API runs one uvicorn
    process, so a blocking call there is not slow *logins*: it is the whole
    service serving nobody for a tenth of a second, catalog and payment
    webhooks included. Roughly ten password checks a second saturated it.

    A ticker measures it directly: with the work on a thread the loop keeps
    turning, and with it inline the tick count is zero.
    """
    ticks = 0
    stop = False

    async def ticker() -> None:
        nonlocal ticks
        while not stop:
            await asyncio.sleep(0.005)
            ticks += 1

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.03)  # let the ticker settle
    before = ticks

    if call == "hash":
        await hash_password("benchmark-probe")
    else:
        await verify_password("benchmark-probe", await hash_password("benchmark-probe"))

    after = ticks
    stop = True
    task.cancel()

    assert after - before >= 3, (
        f"the loop ticked {after - before} times while {call}ing — argon2 is "
        "running inline and starving every other request"
    )


async def test_concurrent_hashing_is_bounded() -> None:
    """Moving argon2 to threads without a cap trades one outage for a worse one.

    anyio's default thread limiter is 40, and each argon2 call allocates
    ``memory_cost`` — 64 MiB. Forty at once is 2.5 GB of transient allocation
    against a 2g container limit on a host with no swap: the OOM killer, which
    on this shared box may well pick the neighbour stack's database. Capping the
    concurrency is what makes the threadpool safe rather than merely faster.
    """
    from yupay.modules.auth import security

    limiter = security.PASSWORD_LIMITER
    assert limiter.total_tokens >= 1
    peak_mib = limiter.total_tokens * security.ARGON2_MEMORY_MIB
    assert peak_mib <= 512, (
        f"{limiter.total_tokens} concurrent hashes is {peak_mib} MiB of transient "
        "allocation — too close to the container limit"
    )


async def test_the_limiter_actually_serialises_beyond_its_capacity() -> None:
    """Guard the wiring, not just the number: the limiter has to be passed to
    `run_sync`, and forgetting that argument is silent."""
    import anyio

    from yupay.modules.auth import security

    # CapacityLimiter.total_tokens is typed float (it accepts math.inf).
    cap = int(security.PASSWORD_LIMITER.total_tokens)
    running = 0
    peak = 0

    def _fake_hash(_plain: str) -> str:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        time_end = __import__("time").perf_counter() + 0.05
        while __import__("time").perf_counter() < time_end:
            pass
        running -= 1
        return "$argon2id$fake"

    original = security.hash_password_sync
    security.hash_password_sync = _fake_hash  # type: ignore[assignment]
    try:
        async with anyio.create_task_group() as tg:
            for _ in range(cap + 4):
                tg.start_soon(security.hash_password, "x")
    finally:
        security.hash_password_sync = original  # type: ignore[assignment]

    assert peak <= cap, f"{peak} ran at once against a cap of {cap}"
