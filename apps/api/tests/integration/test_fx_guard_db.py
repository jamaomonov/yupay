"""Integration tests for the DB-backed half of the FX trust gate.

``check_rate`` (the pure threshold logic) is covered by unit tests in
``tests/unit/test_fx_guard.py``. These tests exercise ``guarded_usd_rate`` and
``_previous_rate`` against a real Postgres database — the ``fx_rates`` history
read, the ``fx_snapshots`` write via :meth:`FxService.snapshot`, and the
``FxUnavailableError`` → ``RateRejected("unavailable", ...)`` translation.

Following the pattern in ``test_fx_routes.py``: patch ``build_default_service``
to return an :class:`FxService` wired to a fake Redis and a stub provider
chain. No outbound HTTP, no real Redis.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import fakeredis.aioredis
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.fx.models import FxRate
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote
from yupay.modules.fx.service import FxService
from yupay.modules.pricing.fx_guard import RateRejected, _previous_rate, guarded_usd_rate

pytestmark = pytest.mark.asyncio


class _StubProvider(FxProvider):
    name = "stub"

    def __init__(self, rates: dict[str, Decimal]) -> None:
        self._rates = rates

    def supports(self, base: str, quote: str) -> bool:
        return base.upper() == "USD" and quote.upper() in self._rates

    async def get_rate(self, base: str, quote: str) -> Quote:
        return Quote(
            base=base.upper(),
            quote=quote.upper(),
            rate=self._rates[quote.upper()],
            fetched_at=now(),
            source=self.name,
        )


class _FailingProvider(FxProvider):
    name = "failing"

    def supports(self, base: str, quote: str) -> bool:
        return True

    async def get_rate(self, base: str, quote: str) -> Quote:
        raise FxProviderError("upstream unreachable")


def _stub_service(rates: dict[str, Decimal]) -> FxService:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return FxService(providers=[_StubProvider(rates)], redis=redis)


def _failing_service() -> FxService:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return FxService(providers=[_FailingProvider()], redis=redis)


async def _insert_fx_rate(
    db: AsyncSession, *, quote: str, rate: Decimal, fetched_at: datetime | None = None
) -> None:
    db.add(
        FxRate(
            id=new_id(),
            base="USD",
            quote=quote,
            rate=rate,
            source="history",
            fetched_at=fetched_at or now(),
        )
    )
    await db.commit()


async def test_a_good_rate_passes_and_is_returned(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "yupay.modules.pricing.fx_guard.build_default_service",
        lambda: _stub_service({"UZS": Decimal("13100")}),
    )
    await _insert_fx_rate(db_session, quote="UZS", rate=Decimal("13000"))

    rate = await guarded_usd_rate(db_session, quote="UZS")

    assert rate == Decimal("13100")


async def test_a_rate_that_deviates_from_the_latest_fx_rates_row_is_rejected(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The failure that motivated the gate: a provider returns a number that
    # looks like a rate but is half the real one.
    monkeypatch.setattr(
        "yupay.modules.pricing.fx_guard.build_default_service",
        lambda: _stub_service({"UZS": Decimal("6500")}),
    )
    await _insert_fx_rate(db_session, quote="UZS", rate=Decimal("13000"))

    with pytest.raises(RateRejected) as exc:
        await guarded_usd_rate(db_session, quote="UZS")

    assert exc.value.reason == "deviation"


async def test_previous_rate_picks_the_most_recent_row_for_the_requested_pair(
    db_session: AsyncSession,
) -> None:
    base_time = now()
    await _insert_fx_rate(
        db_session, quote="UZS", rate=Decimal("12000"), fetched_at=base_time - timedelta(hours=2)
    )
    await _insert_fx_rate(
        db_session, quote="UZS", rate=Decimal("13000"), fetched_at=base_time - timedelta(hours=1)
    )
    # A more recent row, but for a different quote currency — must not be
    # picked up by a USD->UZS lookup.
    await _insert_fx_rate(db_session, quote="RUB", rate=Decimal("999999"), fetched_at=base_time)

    previous = await _previous_rate(db_session, quote="UZS")

    assert previous == Decimal("13000")


async def test_fx_unavailable_surfaces_as_rate_rejected_unavailable(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "yupay.modules.pricing.fx_guard.build_default_service",
        _failing_service,
    )

    with pytest.raises(RateRejected) as exc:
        await guarded_usd_rate(db_session, quote="UZS")

    assert exc.value.reason == "unavailable"
