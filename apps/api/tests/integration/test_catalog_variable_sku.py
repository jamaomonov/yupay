"""A SKU whose amount the customer chooses."""

from __future__ import annotations

from decimal import Decimal

import fakeredis.aioredis
import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote
from yupay.modules.fx.service import FxService

pytestmark = pytest.mark.asyncio


class _FailingProvider(FxProvider):
    """Simulates the whole FX pipeline being down, so the trust gate rejects
    with reason ``unavailable`` — the simplest way to trip it without needing
    an ``fx_rates`` history row."""

    name = "failing"

    def supports(self, base: str, quote: str) -> bool:
        return True

    async def get_rate(self, base: str, quote: str) -> Quote:
        raise FxProviderError("upstream unreachable")


def _failing_fx_service() -> FxService:
    return FxService(
        providers=[_FailingProvider()],
        redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
    )


@pytest.fixture
async def _sku(db_session: AsyncSession) -> Sku:
    """Insert a single Category → Brand → Product → SKU chain for the tests below."""
    category = Category(id=new_id(), slug="wallets", sort_order=10, active=True)
    brand = Brand(
        id=new_id(),
        slug="steam",
        category_id=category.id,
        sort_order=10,
        active=True,
    )
    sku = Sku(
        id=new_id(),
        sku_code="steam-wallet-variable",
        denomination=None,
        region=None,
        price_usd=Decimal("1"),
        sort_order=10,
        active=True,
    )
    product = Product(
        id=new_id(),
        slug="steam-wallet",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        skus=[sku],
    )
    db_session.add(category)
    db_session.add(brand)
    db_session.add(product)
    await db_session.commit()
    return sku


async def test_variable_amount_columns_round_trip(db_session: AsyncSession, _sku: Sku) -> None:
    _sku.variable_amount = True
    _sku.min_amount_usd = Decimal("1.00")
    _sku.max_amount_usd = Decimal("300.00")
    _sku.rate_multiplier = Decimal("1.0800")
    await db_session.flush()
    await db_session.refresh(_sku)
    assert _sku.variable_amount is True
    assert _sku.min_amount_usd == Decimal("1.00")
    assert _sku.rate_multiplier == Decimal("1.0800")


async def test_fixed_skus_default_to_non_variable(db_session: AsyncSession, _sku: Sku) -> None:
    assert _sku.variable_amount is False
    assert _sku.min_amount_usd is None


async def test_variable_amount_rejects_missing_bounds_and_multiplier(
    db_session: AsyncSession, _sku: Sku
) -> None:
    """A variable SKU with no bounds/multiplier at all violates the CHECK."""
    _sku.variable_amount = True
    with pytest.raises(IntegrityError):
        # SAVEPOINT: the failed flush aborts only this nested transaction,
        # leaving db_session usable for the rest of the test.
        async with db_session.begin_nested():
            await db_session.flush()


async def test_variable_amount_rejects_min_greater_than_max(
    db_session: AsyncSession, _sku: Sku
) -> None:
    _sku.variable_amount = True
    _sku.min_amount_usd = Decimal("300.00")
    _sku.max_amount_usd = Decimal("1.00")
    _sku.rate_multiplier = Decimal("1.0800")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_variable_amount_rejects_zero_min_amount(db_session: AsyncSession, _sku: Sku) -> None:
    _sku.variable_amount = True
    _sku.min_amount_usd = Decimal("0")
    _sku.max_amount_usd = Decimal("300.00")
    _sku.rate_multiplier = Decimal("1.0800")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_variable_amount_rejects_zero_rate_multiplier(
    db_session: AsyncSession, _sku: Sku
) -> None:
    _sku.variable_amount = True
    _sku.min_amount_usd = Decimal("1.00")
    _sku.max_amount_usd = Decimal("300.00")
    _sku.rate_multiplier = Decimal("0")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_variable_amount_accepts_equal_min_and_max(
    db_session: AsyncSession, _sku: Sku
) -> None:
    """min_amount_usd == max_amount_usd (a single allowed amount) must be accepted —
    pins that the CHECK isn't over-tight."""
    _sku.variable_amount = True
    _sku.min_amount_usd = Decimal("50.00")
    _sku.max_amount_usd = Decimal("50.00")
    _sku.rate_multiplier = Decimal("1.0800")
    await db_session.flush()
    await db_session.refresh(_sku)
    assert _sku.min_amount_usd == _sku.max_amount_usd == Decimal("50.00")


# ---------- catalog read path: display_price ----------


async def test_variable_sku_reports_no_price_when_the_rate_is_rejected(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    _sku: Sku,
) -> None:
    """With the FX guard tripped the SKU comes back with display_price=None so
    the storefront renders "temporarily unavailable" instead of a zero."""
    _sku.variable_amount = True
    _sku.min_amount_usd = Decimal("1.00")
    _sku.max_amount_usd = Decimal("300.00")
    _sku.rate_multiplier = Decimal("1.0800")
    await db_session.commit()

    monkeypatch.setattr(
        "yupay.modules.pricing.fx_guard.build_default_service",
        _failing_fx_service,
    )

    r = await integration_client.get(f"/api/v1/catalog/skus/{_sku.id}?currency=UZS")
    assert r.status_code == 200, r.text
    assert r.json()["display_price"] is None


async def test_variable_sku_fields_surface_on_the_catalog_read_path(
    integration_client: AsyncClient, db_session: AsyncSession, _sku: Sku
) -> None:
    """variable_amount / min_amount_usd / max_amount_usd must reach the
    storefront response — without them the client can't tell this SKU takes
    a customer-chosen amount at all, let alone render the right bounds."""
    _sku.variable_amount = True
    _sku.min_amount_usd = Decimal("1.00")
    _sku.max_amount_usd = Decimal("300.00")
    _sku.rate_multiplier = Decimal("1.0800")
    await db_session.commit()

    r = await integration_client.get(f"/api/v1/catalog/skus/{_sku.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["variable_amount"] is True
    assert Decimal(body["min_amount_usd"]) == Decimal("1.00")
    assert Decimal(body["max_amount_usd"]) == Decimal("300.00")
