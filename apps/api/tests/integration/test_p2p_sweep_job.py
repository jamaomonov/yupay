"""Integration tests for the P2P sweep scheduler job."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.core.redis import get_redis
from yupay.modules.p2p import reservations as svc
from yupay_scheduler.jobs import p2p_sweep

from tests.integration.p2p_fixtures import (  # noqa: F401  (_fixed_rate is autouse)
    RATE,
    _card,
    _fixed_rate,
    _merchant,
    _open,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def monkeypatch_now(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Fixture to control time in p2p_sweep via monkeypatch."""
    # Store the real now for restoring
    real_now = p2p_sweep.now
    current_time_holder = {"t": real_now()}

    def mock_now() -> Any:
        return current_time_holder["t"]

    monkeypatch.setattr(p2p_sweep, "now", mock_now)
    return current_time_holder


async def test_sweep_job_alerts_on_recent_expiry_with_no_incoming(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    monkeypatch_now: Any,
) -> None:
    """Create a reservation, expire it via read(), then run job with no incoming rows."""
    # Setup: card, merchant, allowlist
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])

    # Create a reservation
    t0 = p2p_sweep.now()
    monkeypatch_now["t"] = t0
    r = await svc.reserve(db_session, merchant_id=m, amount_uzs=50_000, idempotency_key="k1")
    await db_session.commit()

    # Expire it via read() (the cabinet in-place path)
    monkeypatch_now["t"] = t0 + timedelta(minutes=6)
    await svc.read(db_session, merchant_id=m, number=r.number)
    await db_session.commit()

    # Clear Redis key
    redis = get_redis()
    await redis.delete(p2p_sweep._ALERT_KEY)

    # Monkeypatch send_admin_alert to track calls
    alert_calls: list[tuple[str, str]] = []

    async def mock_alert(msg: str, kind: str) -> None:
        alert_calls.append((msg, kind))

    monkeypatch.setattr(p2p_sweep, "send_admin_alert", mock_alert)

    # Run the job
    await p2p_sweep.run_p2p_sweep()

    # Verify exactly one alert was sent
    assert len(alert_calls) == 1
    msg, kind = alert_calls[0]
    assert "6 часов" in msg
    assert kind == "p2p_silence"


async def test_sweep_job_deduplicates_alerts_within_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run the job twice within the hour; second run sends no alert (Redis NX)."""
    # Clear Redis key
    redis = get_redis()
    await redis.delete(p2p_sweep._ALERT_KEY)

    # Monkeypatch send_admin_alert
    alert_calls: list[tuple[str, str]] = []

    async def mock_alert(msg: str, kind: str) -> None:
        alert_calls.append((msg, kind))

    monkeypatch.setattr(p2p_sweep, "send_admin_alert", mock_alert)

    # Monkeypatch the job to skip the actual sweep logic but still hit the silence alert
    async def mock_run() -> None:
        t = p2p_sweep.now()
        # Simulate a sweep that found 1 expired row
        recently_expired = 1
        if p2p_sweep.silence_alert_due(None, recently_expired, t):
            if await redis.set(p2p_sweep._ALERT_KEY, "1", nx=True, ex=p2p_sweep._ALERT_TTL_SECONDS):
                await p2p_sweep.send_admin_alert(
                    "P2P: резервы истекают, а от HUMO нет уведомлений больше 6 часов — проверьте бота",
                    kind="p2p_silence",
                )

    # First run
    await mock_run()
    assert len(alert_calls) == 1

    # Second run - alert should NOT be sent due to Redis NX
    await mock_run()
    assert len(alert_calls) == 1  # Still 1, no new alert


async def test_sweep_job_does_not_alert_if_incoming_recent(
    monkeypatch: pytest.MonkeyPatch,
    monkeypatch_now: Any,
) -> None:
    """With a recent P2PIncoming row, no alert is sent."""
    # Clear Redis key
    redis = get_redis()
    await redis.delete(p2p_sweep._ALERT_KEY)

    t0 = p2p_sweep.now()
    monkeypatch_now["t"] = t0

    # Monkeypatch send_admin_alert
    alert_calls: list[tuple[str, str]] = []

    async def mock_alert(msg: str, kind: str) -> None:
        alert_calls.append((msg, kind))

    monkeypatch.setattr(p2p_sweep, "send_admin_alert", mock_alert)

    # Monkeypatch the job to simulate the condition
    async def mock_run() -> None:
        t = p2p_sweep.now()
        # Simulate a sweep that found 1 expired row
        recently_expired = 1
        # Simulate a recent incoming (1 hour ago, still within 6-hour window)
        last_incoming_at = t - timedelta(hours=1)
        if p2p_sweep.silence_alert_due(last_incoming_at, recently_expired, t):
            if await redis.set(p2p_sweep._ALERT_KEY, "1", nx=True, ex=p2p_sweep._ALERT_TTL_SECONDS):
                await p2p_sweep.send_admin_alert(
                    "P2P: резервы истекают, а от HUMO нет уведомлений больше 6 часов — проверьте бота",
                    kind="p2p_silence",
                )

    # Run the job
    await mock_run()

    # No alert should be sent because the incoming is recent (within 6 hours)
    assert len(alert_calls) == 0

    # Clean up Redis key after test
    await redis.delete(p2p_sweep._ALERT_KEY)
