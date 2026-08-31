"""Supplier-catalog watchdog: a mapped position the supplier delisted must
deactivate our SKU and ping the admin chat — after two consecutive misses,
never off the back of a supplier outage.

The two-strike rule is the load-bearing part: an hourly tick that
mass-deactivated the shelf because G2B had a bad five minutes would be worse
than the problem it solves. A miss only stamps the mapping; the NEXT tick,
at least ``_CONFIRM_AFTER`` later, acts on a stamp that is still warm.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.integrations.catalog_watch import (
    _CONFIRM_AFTER,
    watch_mapped_variants,
)
from yupay.modules.integrations.models import SkuSupplierMapping

pytestmark = pytest.mark.asyncio


class _FakeClient:
    """games_catalogue/fetch_product double with scriptable answers."""

    def __init__(
        self,
        games: dict[str, list[dict[str, Any]] | Exception],
        vouchers: dict[str, dict[str, Any] | None | Exception] | None = None,
    ) -> None:
        self.games = games
        self.vouchers = vouchers or {}

    async def games_catalogue(self, game_code: str) -> list[dict[str, Any]]:
        answer = self.games[game_code]
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def fetch_product(self, product_id: str) -> dict[str, Any] | None:
        answer = self.vouchers[product_id]
        if isinstance(answer, Exception):
            raise answer
        return answer


class _AlertSpy:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def __call__(self, text: str, *, kind: str = "unspecified") -> bool:
        self.sent.append((text, kind))
        return True


async def _seed(
    db: AsyncSession,
    *,
    kind: str = "game",
    external_product_id: str = "pubgm",
    external_variant_id: str | None = "1800 UC (discounted)",
) -> tuple[Sku, SkuSupplierMapping]:
    suffix = uuid.uuid4().hex[:8]
    category = Category(id=new_id(), slug=f"games-{suffix}", sort_order=0, active=True)
    db.add(category)
    await db.flush()
    brand = Brand(
        id=new_id(), slug=f"brand-{suffix}", category_id=category.id, sort_order=0, active=True
    )
    db.add(brand)
    await db.flush()
    product = Product(
        id=new_id(),
        slug=f"product-{suffix}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=0,
        active=True,
        required_fields=[],
    )
    db.add(product)
    await db.flush()
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"watch-{suffix}",
        denomination="1800 UC",
        region="WW",
        price_usd=Decimal("27.00"),
        sort_order=0,
        active=True,
    )
    db.add(sku)
    await db.flush()
    mapping = SkuSupplierMapping(
        sku_id=sku.id,
        supplier_slug="g2b",
        kind=kind,
        external_product_id=external_product_id,
        external_variant_id=external_variant_id,
        extra={},
        is_active=True,
    )
    db.add(mapping)
    await db.flush()
    return sku, mapping


async def test_first_miss_only_stamps(db_session: AsyncSession) -> None:
    sku, mapping = await _seed(db_session)
    alerts = _AlertSpy()
    client = _FakeClient(games={"pubgm": [{"name": "60"}]})  # variant gone, catalogue alive

    report = await watch_mapped_variants(db_session, client=client, send_alert=alerts)

    await db_session.refresh(sku)
    await db_session.refresh(mapping)
    assert sku.active is True
    assert "catalog_missing_since" in mapping.extra
    assert alerts.sent == []
    assert report.stamped == 1
    assert report.deactivated == 0


async def test_second_miss_deactivates_and_alerts(db_session: AsyncSession) -> None:
    sku, mapping = await _seed(db_session)
    stale = (now() - _CONFIRM_AFTER - timedelta(minutes=1)).isoformat()
    mapping.extra = {"catalog_missing_since": stale}
    await db_session.flush()
    alerts = _AlertSpy()
    client = _FakeClient(games={"pubgm": [{"name": "60"}]})

    report = await watch_mapped_variants(db_session, client=client, send_alert=alerts)

    await db_session.refresh(sku)
    await db_session.refresh(mapping)
    assert sku.active is False
    assert mapping.is_active is True  # the mapping is the watch's memory — it stays
    assert mapping.extra.get("catalog_watch_deactivated") is True
    assert len(alerts.sent) == 1
    text, alert_kind = alerts.sent[0]
    assert sku.sku_code in text
    assert "1800 UC (discounted)" in text
    assert alert_kind == "catalog_watch"
    assert report.deactivated == 1

    # A third tick must not spam: already-acted mappings are skipped.
    report2 = await watch_mapped_variants(db_session, client=client, send_alert=alerts)
    assert len(alerts.sent) == 1
    assert report2.deactivated == 0


async def test_young_stamp_is_not_acted_on(db_session: AsyncSession) -> None:
    sku, mapping = await _seed(db_session)
    mapping.extra = {"catalog_missing_since": now().isoformat()}
    await db_session.flush()
    alerts = _AlertSpy()
    client = _FakeClient(games={"pubgm": [{"name": "60"}]})

    await watch_mapped_variants(db_session, client=client, send_alert=alerts)

    await db_session.refresh(sku)
    assert sku.active is True
    assert alerts.sent == []


async def test_supplier_outage_stamps_nothing(db_session: AsyncSession) -> None:
    _, mapping = await _seed(db_session)
    alerts = _AlertSpy()
    for broken in (
        _FakeClient(games={"pubgm": RuntimeError("boom")}),
        _FakeClient(games={"pubgm": []}),  # an empty catalogue smells like an outage too
    ):
        await watch_mapped_variants(db_session, client=broken, send_alert=alerts)
        await db_session.refresh(mapping)
        assert "catalog_missing_since" not in mapping.extra
    assert alerts.sent == []


async def test_reappearance_clears_a_pending_stamp_quietly(db_session: AsyncSession) -> None:
    sku, mapping = await _seed(db_session)
    mapping.extra = {"catalog_missing_since": now().isoformat()}
    await db_session.flush()
    alerts = _AlertSpy()
    client = _FakeClient(games={"pubgm": [{"name": "1800 UC (discounted)"}]})

    await watch_mapped_variants(db_session, client=client, send_alert=alerts)

    await db_session.refresh(mapping)
    await db_session.refresh(sku)
    assert "catalog_missing_since" not in mapping.extra
    assert sku.active is True
    assert alerts.sent == []


async def test_reappearance_after_deactivation_alerts_but_keeps_sku_off(
    db_session: AsyncSession,
) -> None:
    sku, mapping = await _seed(db_session)
    sku.active = False
    mapping.extra = {
        "catalog_missing_since": (now() - timedelta(hours=3)).isoformat(),
        "catalog_watch_deactivated": True,
    }
    await db_session.flush()
    alerts = _AlertSpy()
    client = _FakeClient(games={"pubgm": [{"name": "1800 UC (discounted)"}]})

    report = await watch_mapped_variants(db_session, client=client, send_alert=alerts)

    await db_session.refresh(mapping)
    await db_session.refresh(sku)
    assert sku.active is False  # prices may have moved — a human re-enables
    assert "catalog_watch_deactivated" not in mapping.extra
    assert "catalog_missing_since" not in mapping.extra
    assert len(alerts.sent) == 1
    assert "снова в каталоге" in alerts.sent[0][0]
    assert report.reappeared == 1


async def test_voucher_mapping_watches_fetch_product(db_session: AsyncSession) -> None:
    sku, mapping = await _seed(
        db_session, kind="voucher", external_product_id="steam-10-us", external_variant_id=None
    )
    stale = (now() - _CONFIRM_AFTER - timedelta(minutes=1)).isoformat()
    mapping.extra = {"catalog_missing_since": stale}
    await db_session.flush()
    alerts = _AlertSpy()
    client = _FakeClient(games={}, vouchers={"steam-10-us": None})

    report = await watch_mapped_variants(db_session, client=client, send_alert=alerts)

    await db_session.refresh(sku)
    assert sku.active is False
    assert len(alerts.sent) == 1
    assert "steam-10-us" in alerts.sent[0][0]
    assert report.deactivated == 1


async def test_voucher_fetch_error_is_not_a_miss(db_session: AsyncSession) -> None:
    _, mapping = await _seed(
        db_session, kind="voucher", external_product_id="steam-10-us", external_variant_id=None
    )
    alerts = _AlertSpy()
    client = _FakeClient(games={}, vouchers={"steam-10-us": RuntimeError("timeout")})

    await watch_mapped_variants(db_session, client=client, send_alert=alerts)

    await db_session.refresh(mapping)
    assert "catalog_missing_since" not in mapping.extra
    assert alerts.sent == []
