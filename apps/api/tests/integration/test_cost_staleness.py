"""``integrations.cost_staleness`` — whose cost has no recent supplier answer.

Pins what counts as stale (old or never-stamped cost on a SKU with a live
price-collecting mapping) and what does not: a fresh stamp, a SKU with no
such mapping, one pinned to the warehouse by a sourcing rule, and one with
no cost at all. Also pins that writing a cost stamps the clock.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.modules.catalog import admin_service as catalog_svc
from yupay.modules.catalog.models import Sku
from yupay.modules.integrations import cost_staleness
from yupay.modules.sourcing.models import SkuSourcingRule

from tests.integration.test_admin_fulfillment_reassign_options import _map
from tests.integration.test_sku_cost_margin import _seed_sku

pytestmark = pytest.mark.asyncio


async def _stamp(db: AsyncSession, sku_id: str, *, hours_ago: int | None) -> None:
    sku = await db.get(Sku, sku_id)
    assert sku is not None
    sku.cost_synced_at = None if hours_ago is None else now() - timedelta(hours=hours_ago)
    await db.commit()


async def test_find_stale_picks_old_and_never_but_not_fresh_unmapped_or_pinned(
    db_session: AsyncSession,
) -> None:
    old = await _seed_sku(
        db_session, "old", cost_usdt="1.00", price_usd="1.13", margin_percent="13"
    )
    await _map(db_session, old, "g2b")
    await _stamp(db_session, old, hours_ago=9)

    never = await _seed_sku(
        db_session, "never", cost_usdt="1.00", price_usd="1.13", margin_percent="13"
    )
    await _map(db_session, never, "fzr")
    await _map(db_session, never, "nova")
    await _stamp(db_session, never, hours_ago=None)

    fresh = await _seed_sku(
        db_session, "fresh", cost_usdt="1.00", price_usd="1.13", margin_percent="13"
    )
    await _map(db_session, fresh, "g2b")
    await _stamp(db_session, fresh, hours_ago=1)

    # Mapped only to a supplier whose prices are not collected: nothing to be
    # stale against.
    unpriced = await _seed_sku(
        db_session, "unpriced", cost_usdt="1.00", price_usd="1.13", margin_percent="13"
    )
    await _map(db_session, unpriced, "mock")
    await _stamp(db_session, unpriced, hours_ago=99)

    # Pinned to the warehouse: the supplier mapping is not the route.
    pinned = await _seed_sku(
        db_session, "pinned", cost_usdt="1.00", price_usd="1.13", margin_percent="13"
    )
    await _map(db_session, pinned, "g2b")
    db_session.add(SkuSourcingRule(sku_id=pinned, mode="force_inventory", updated_by="test"))
    await db_session.commit()
    await _stamp(db_session, pinned, hours_ago=99)

    # No cost: unpriced, not stale.
    nocost = await _seed_sku(
        db_session, "nocost", cost_usdt=None, price_usd="1.13", margin_percent=None
    )
    await _map(db_session, nocost, "g2b")

    stale = await cost_staleness.find_stale(db_session, max_age=timedelta(hours=6))

    assert stale.total == 2
    assert [r.sku_code for r in stale.rows] == ["sk-never", "sk-old"]  # never first
    assert stale.rows[0].suppliers in ("fzr,nova", "nova,fzr")
    assert stale.by_supplier == {"g2b": 1, "fzr": 1, "nova": 1}


async def test_format_alert_names_total_suppliers_and_rows(db_session: AsyncSession) -> None:
    old = await _seed_sku(
        db_session, "fmt", cost_usdt="1.00", price_usd="1.13", margin_percent="13"
    )
    await _map(db_session, old, "g2b")
    await _stamp(db_session, old, hours_ago=30)

    stale = await cost_staleness.find_stale(db_session, max_age=timedelta(hours=6))
    text = cost_staleness.format_alert(stale, max_age=timedelta(hours=6))

    assert "1 SKU без ответа поставщика дольше 6 ч" in text
    assert "g2b — 1" in text
    assert "br-fmt/sk-fmt" in text
    assert "30 ч назад" in text


async def test_writing_a_cost_stamps_the_clock_even_when_it_did_not_move(
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_sku(
        db_session, "stamp", cost_usdt="1.00", price_usd="1.13", margin_percent="13"
    )
    await _stamp(db_session, sku_id, hours_ago=9)

    await catalog_svc.set_sku_cost_usdt(db_session, sku_id=sku_id, new_cost=Decimal("1.00"))
    await db_session.commit()

    synced = (
        await db_session.execute(select(Sku.cost_synced_at).where(Sku.id == sku_id))
    ).scalar_one()
    assert synced is not None
    assert now() - synced < timedelta(minutes=1)
