"""The csmarket feed lands on the same rows as Waxpeer's snapshot (ADR-0098)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.modules.fulfillment.suppliers.csmarket_client import FeedItem
from yupay.modules.skins.bymykel import dedupe, rows_from_skins, upsert_items
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.prices import apply_prices
from yupay.modules.skins.prices_csmarket import aggregate_feed, key_of

pytestmark = pytest.mark.asyncio
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skins"


def _item(item_id: str, slug: str, name: str, units: int, stock: int = 3) -> FeedItem:
    return FeedItem(
        item_id=item_id,
        slug=slug,
        market_hash_name=name,
        exterior=None,
        price_units=units,
        stock=stock,
        retail_price_units=None,
        updated_at=datetime(2026, 10, 9, tzinfo=UTC),
    )


def _feed() -> list[FeedItem]:
    return [
        _item("csm-ak", "ak-47-redline-field-tested", "AK-47 | Redline (Field-Tested)", 26100),
        _item(
            "csm-kara",
            "karambit-doppler-factory-new-phase-2",
            "★ Karambit | Doppler (Factory New)",
            1400000,
        ),
        _item("csm-out", "awp-sold-out-field-tested", "AWP | Sold Out (Field-Tested)", 100, 0),
    ]


async def _aiter(items: list[FeedItem]) -> AsyncIterator[FeedItem]:
    for item in items:
        yield item


async def _seed(db: AsyncSession) -> None:
    rows = dedupe(rows_from_skins(json.loads((FIXTURES / "bymykel_skins.json").read_text())))
    await upsert_items(db, rows)
    await db.commit()


async def _by_slug(db: AsyncSession, slug: str) -> SkinItem:
    db.expire_all()
    return (await db.execute(select(SkinItem).where(SkinItem.slug == slug))).scalar_one()


async def test_phase_is_read_back_from_the_slug() -> None:
    feed = _feed()
    assert key_of(feed[0]) == ("AK-47 | Redline (Field-Tested)", "")
    assert key_of(feed[1]) == ("★ Karambit | Doppler (Factory New)", "Phase 2")
    inline = _item("x", "whatever", "★ Karambit | Doppler Ruby (Factory New)", 1)
    assert key_of(inline) == ("★ Karambit | Doppler (Factory New)", "Ruby")
    suffixed = _item("y", "ak-47-redline-field-tested-2", "AK-47 | Redline (Field-Tested)", 1)
    assert key_of(suffixed) == ("AK-47 | Redline (Field-Tested)", "")


async def test_out_of_stock_items_are_left_out_and_duplicates_keep_the_cheaper() -> None:
    feed = [
        *_feed(),
        _item("csm-ak-dear", "ak-47-redline-field-tested", "AK-47 | Redline (Field-Tested)", 30000),
    ]
    aggregates, ids = await aggregate_feed(_aiter(feed))
    assert ("AWP | Sold Out (Field-Tested)", "") not in aggregates
    ak = ("AK-47 | Redline (Field-Tested)", "")
    assert aggregates[ak].min_auto == 26100
    assert aggregates[ak].count_auto == 3
    assert aggregates[ak].cheapest == []
    assert ids[ak] == "csm-ak"


async def test_feed_lands_on_bymykel_rows_with_ids_and_keeps_steam_price(
    db_session: AsyncSession,
) -> None:
    await _seed(db_session)
    await db_session.execute(
        update(SkinItem)
        .where(SkinItem.slug == "ak-47-redline-field-tested")
        .values(steam_price_units=43794)
    )
    await db_session.commit()

    aggregates, ids = await aggregate_feed(_aiter(_feed()))
    result = await apply_prices(db_session, aggregates, meta=None, at=now(), source_ids=ids)
    await db_session.commit()
    assert result.changed == 2

    ak = await _by_slug(db_session, "ak-47-redline-field-tested")
    assert (ak.min_auto_units, ak.count_auto, ak.active) == (26100, 3, True)
    assert ak.source_item_id == "csm-ak"
    assert ak.steam_price_units == 43794  # the feed has none: the last value stands
    assert ak.cheapest_auto == []
    knife = await _by_slug(db_session, "karambit-doppler-factory-new-phase-2")
    assert (knife.min_auto_units, knife.source_item_id) == (1400000, "csm-kara")


async def test_a_new_id_with_the_same_price_is_still_written(db_session: AsyncSession) -> None:
    await _seed(db_session)
    aggregates, ids = await aggregate_feed(_aiter(_feed()))
    await apply_prices(db_session, aggregates, meta=None, at=now(), source_ids=ids)
    await db_session.commit()
    again = await apply_prices(db_session, aggregates, meta=None, at=now(), source_ids=ids)
    assert again.changed == 0

    ak = ("AK-47 | Redline (Field-Tested)", "")
    moved = {**ids, ak: "csm-ak-relisted"}
    result = await apply_prices(db_session, aggregates, meta=None, at=now(), source_ids=moved)
    await db_session.commit()
    assert result.changed == 1
    assert (await _by_slug(db_session, "ak-47-redline-field-tested")).source_item_id == (
        "csm-ak-relisted"
    )


async def test_items_missing_from_the_feed_go_inactive(db_session: AsyncSession) -> None:
    await _seed(db_session)
    aggregates, ids = await aggregate_feed(_aiter(_feed()))
    await apply_prices(db_session, aggregates, meta=None, at=now(), source_ids=ids)
    await db_session.commit()
    only_ak = {k: v for k, v in aggregates.items() if k[0].startswith("AK-47")}
    result = await apply_prices(db_session, only_ak, meta=None, at=now(), source_ids=ids)
    await db_session.commit()
    assert result.deactivated == 1
    assert (await _by_slug(db_session, "karambit-doppler-factory-new-phase-2")).active is False
