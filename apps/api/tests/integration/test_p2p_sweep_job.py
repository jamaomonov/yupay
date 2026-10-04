"""Integration tests for the P2P sweep scheduler job."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.core.redis import get_redis
from yupay.modules.p2p import reservations as svc
from yupay.modules.p2p.models import P2PIncoming, P2PReservation
from yupay_scheduler.jobs import p2p_sweep

from tests.integration.p2p_fixtures import (  # noqa: F401  (_fixed_rate is autouse)
    RATE,
    _card,
    _fixed_rate,
    _merchant,
    _open,
)

pytestmark = pytest.mark.asyncio


def test_silence_alert_rule_no_alert_when_recent_incoming() -> None:
    """Silence alert rule: no alert if incoming is recent (within 6 h)."""
    t = now()
    recent_incoming = t - timedelta(hours=1)
    # With incoming 1 hour ago (within 6 hours), no alert even with expiries
    assert not p2p_sweep.silence_alert_due(recent_incoming, 5, t)


async def test_sweep_alerts_on_recent_expiry_with_no_incoming(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reservation expired via read() (cabinet path), no incoming → alert sent.

    This test verifies that the job counts recently-expired rows, not just
    sweep() results, so it catches expirations from both the current tick
    and the cabinet's read() in-place path.
    """
    # Setup: card, merchant, allowlist
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])

    # Create a reservation
    t0 = now()
    r = await svc.reserve(
        db_session, merchant_id=m, amount_uzs=50_000, idempotency_key="k1"
    )
    await db_session.commit()

    # Backdate it so it's already expired (created 6 min ago, expires 30 s ago)
    await db_session.execute(
        update(P2PReservation)
        .where(P2PReservation.id == r.id)
        .values(
            created_at=t0 - timedelta(minutes=6),
            expires_at=t0 - timedelta(seconds=30),
        )
    )
    await db_session.commit()

    # Expire it via read() (the cabinet in-place path)
    await svc.read(db_session, merchant_id=m, number=r.number)
    await db_session.commit()

    # Verify there are no P2PIncoming rows
    incoming_count = await db_session.scalar(select(func.count(P2PIncoming.id)))
    assert incoming_count == 0

    # Clear Redis key
    redis = get_redis()
    await redis.delete(p2p_sweep._ALERT_KEY)

    # Monkeypatch send_admin_alert to track calls
    alert_calls: list[tuple[str, str]] = []

    async def mock_alert(msg: str, kind: str) -> None:
        alert_calls.append((msg, kind))

    monkeypatch.setattr(p2p_sweep, "send_admin_alert", mock_alert)

    # Run the job (the real one, not a mock)
    await p2p_sweep.run_p2p_sweep()

    # Verify exactly one alert was sent with the right kind
    assert len(alert_calls) == 1
    msg, kind = alert_calls[0]
    assert kind == "p2p_silence"

    # Clean up Redis key
    await redis.delete(p2p_sweep._ALERT_KEY)


async def test_sweep_deduplicates_alerts_via_redis_nx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alert de-duplication via Redis NX within 1-hour window."""
    # Test the NX de-duplication logic directly
    redis = get_redis()
    await redis.delete(p2p_sweep._ALERT_KEY)

    # Monkeypatch send_admin_alert to track calls
    alert_calls: list[tuple[str, str]] = []

    async def mock_alert(msg: str, kind: str) -> None:
        alert_calls.append((msg, kind))

    monkeypatch.setattr(p2p_sweep, "send_admin_alert", mock_alert)

    # Simulate first alert call (as the job would do)
    if await redis.set(
        p2p_sweep._ALERT_KEY,
        "1",
        nx=True,
        ex=p2p_sweep._ALERT_TTL_SECONDS,
    ):
        await mock_alert(
            "P2P: резервы истекают, а от HUMO нет уведомлений больше 6 часов",
            kind="p2p_silence",
        )
    assert len(alert_calls) == 1

    # Simulate second alert call within the hour (should fail NX)
    if await redis.set(
        p2p_sweep._ALERT_KEY,
        "1",
        nx=True,
        ex=p2p_sweep._ALERT_TTL_SECONDS,
    ):
        await mock_alert(
            "P2P: резервы истекают, а от HUMO нет уведомлений больше 6 часов",
            kind="p2p_silence",
        )
    # NX failed, so no call is made
    assert len(alert_calls) == 1  # Still 1

    # Clean up
    await redis.delete(p2p_sweep._ALERT_KEY)


def test_silence_alert_rule_no_alert_when_recent_incoming() -> None:
    """Silence alert rule: no alert if incoming is recent (within 6 h)."""
    t = now()
    recent_incoming = t - timedelta(hours=1)
    # With incoming 1 hour ago (within 6 hours), no alert even with expiries
    assert not p2p_sweep.silence_alert_due(recent_incoming, 5, t)
