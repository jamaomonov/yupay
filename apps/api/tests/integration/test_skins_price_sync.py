"""Changed rows only; manual-only names go inactive; unknown names become stubs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.modules.fulfillment.suppliers.waxpeer_client import SnapshotRow
from yupay.modules.skins.bymykel import dedupe, rows_from_skins, upsert_items
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.prices import aggregate, apply_prices

pytestmark = pytest.mark.asyncio
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skins"


def _snapshot() -> list[SnapshotRow]:
    return [
        SnapshotRow(1, "AK-47 | Redline (Field-Tested)", 27867, True),
        SnapshotRow(2, "AK-47 | Redline (Field-Tested)", 27000, False),
        SnapshotRow(3, "★ Karambit | Doppler Phase 2 (Factory New)", 1450000, True),
        SnapshotRow(4, "AWP | Manual Only (Field-Tested)", 5000, False),
    ]


def _meta() -> list[dict[str, object]]:
    return json.loads((FIXTURES / "prices.json").read_text())["items"]  # type: ignore[no-any-return]


async def _seed(db: AsyncSession) -> None:
    rows = dedupe(rows_from_skins(json.loads((FIXTURES / "bymykel_skins.json").read_text())))
    await upsert_items(db, rows)
    await db.commit()


async def _by_slug(db: AsyncSession, slug: str) -> SkinItem:
    db.expire_all()
    return (await db.execute(select(SkinItem).where(SkinItem.slug == slug))).scalar_one()


async def test_prices_land_on_bymykel_rows_including_the_phase(db_session: AsyncSession) -> None:
    await _seed(db_session)
    result = await apply_prices(db_session, aggregate(_snapshot()), meta=_meta(), at=now())
    await db_session.commit()
    assert result.changed == 2  # AK + Karambit; the StatTrak row is not in the snapshot
    ak = await _by_slug(db_session, "ak-47-redline-field-tested")
    assert (ak.min_auto_units, ak.count_auto, ak.min_all_units, ak.count_all) == (
        27867,
        1,
        27000,
        2,
    )
    assert ak.active is True
    assert ak.steam_price_units == 43794
    assert ak.cheapest_auto == [{"listing_id": 1, "price_units": 27867}]
    knife = await _by_slug(db_session, "karambit-doppler-factory-new-phase-2")
    assert knife.min_auto_units == 1450000
    assert knife.source == "bymykel"


async def test_unknown_name_becomes_a_stub_without_waxpeer_image(db_session: AsyncSession) -> None:
    await _seed(db_session)
    result = await apply_prices(db_session, aggregate(_snapshot()), meta=_meta(), at=now())
    await db_session.commit()
    assert result.stubs == 1
    awp = await _by_slug(db_session, "awp-manual-only-field-tested")
    assert (awp.source, awp.category, awp.image_url) == ("stub", "rifles", None)
    assert (awp.active, awp.min_auto_units, awp.count_all) == (False, None, 1)


async def test_second_identical_tick_changes_nothing(db_session: AsyncSession) -> None:
    await _seed(db_session)
    await apply_prices(db_session, aggregate(_snapshot()), meta=_meta(), at=now())
    await db_session.commit()
    result = await apply_prices(db_session, aggregate(_snapshot()), meta=_meta(), at=now())
    assert (result.changed, result.stubs, result.deactivated) == (0, 0, 0)


async def test_name_gone_from_snapshot_goes_inactive(db_session: AsyncSession) -> None:
    await _seed(db_session)
    await apply_prices(db_session, aggregate(_snapshot()), meta=_meta(), at=now())
    await db_session.commit()
    result = await apply_prices(db_session, aggregate(_snapshot()[2:]), meta=_meta(), at=now())
    await db_session.commit()
    assert result.deactivated == 1
    ak = await _by_slug(db_session, "ak-47-redline-field-tested")
    assert (ak.active, ak.min_auto_units, ak.count_auto, ak.cheapest_auto) == (False, None, 0, [])
