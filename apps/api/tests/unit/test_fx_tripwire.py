"""FX drop tripwire: alert + maintenance only when something actually changes."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from yupay.modules.fx.drop_detect import RateDrop
from yupay.modules.fx.tripwire import apply_drop_tripwire, commit_refresh_and_trip

DROP = RateDrop(
    quote="UZS",
    previous=Decimal("12700"),
    current=Decimal("11000"),
    drop_pct=Decimal("13.4"),
)


@pytest.mark.asyncio
async def test_empty_drops_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    trip = AsyncMock(return_value=["wallet"])
    sched = MagicMock()
    monkeypatch.setattr("yupay.modules.fx.tripwire.trip_active_to_maintenance", trip)
    monkeypatch.setattr("yupay.modules.fx.tripwire.schedule_after_commit", sched)

    changed = await apply_drop_tripwire(SimpleNamespace(), [])  # type: ignore[arg-type]

    assert changed == []
    trip.assert_not_called()
    sched.assert_not_called()


@pytest.mark.asyncio
async def test_trips_and_pages_ops_when_a_drop_is_new(monkeypatch: pytest.MonkeyPatch) -> None:
    trip = AsyncMock(return_value=["click", "wallet"])
    alert = AsyncMock(return_value=True)
    sched = MagicMock()
    monkeypatch.setattr("yupay.modules.fx.tripwire.trip_active_to_maintenance", trip)
    monkeypatch.setattr("yupay.modules.fx.tripwire.send_admin_alert", alert)
    monkeypatch.setattr("yupay.modules.fx.tripwire.schedule_after_commit", sched)

    db = SimpleNamespace()
    changed = await apply_drop_tripwire(db, [DROP])  # type: ignore[arg-type]

    assert changed == ["click", "wallet"]
    trip.assert_awaited_once()
    sched.assert_called_once()
    scheduled = sched.call_args
    assert scheduled is not None
    assert scheduled.args[0] is db
    await scheduled.args[1]()
    alert.assert_awaited_once()
    called = alert.await_args
    assert called is not None
    assert called.kwargs["kind"] == "fx_drop"


@pytest.mark.asyncio
async def test_already_down_does_not_repage(monkeypatch: pytest.MonkeyPatch) -> None:
    trip = AsyncMock(return_value=[])
    sched = MagicMock()
    monkeypatch.setattr("yupay.modules.fx.tripwire.trip_active_to_maintenance", trip)
    monkeypatch.setattr("yupay.modules.fx.tripwire.schedule_after_commit", sched)

    changed = await apply_drop_tripwire(SimpleNamespace(), [DROP])  # type: ignore[arg-type]

    assert changed == []
    sched.assert_not_called()


@pytest.mark.asyncio
async def test_commit_refresh_persists_trip_before_caller_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admin listing after this helper can 503 without undoing maintenance."""
    order: list[str] = []

    async def _trip(_db: object) -> tuple[list[object], list[str]]:
        order.append("trip")
        return [], ["wallet"]

    async def _commit() -> None:
        order.append("commit")

    db = AsyncMock()
    db.commit = AsyncMock(side_effect=_commit)
    monkeypatch.setattr("yupay.modules.fx.tripwire.refresh_and_trip", _trip)

    drops, tripped = await commit_refresh_and_trip(db)

    assert drops == []
    assert tripped == ["wallet"]
    assert order == ["trip", "commit"]
