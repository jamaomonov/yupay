"""Regressions from the whole-branch review of the skins catalogue, on shapes
taken from real ByMykel and Waxpeer data (2026-09-28)."""

from __future__ import annotations

from decimal import Decimal

import fakeredis.aioredis
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from yupay.core import config as cfg
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.fulfillment.suppliers.waxpeer_client import SnapshotRow
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.quote_settings import ManualOverride
from yupay.modules.skins.bymykel import dedupe, rows_from_file, rows_from_skins, upsert_items
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.prices import aggregate, apply_prices, sync_prices
from yupay.modules.skins.pricing import DEFAULT_RULES
from yupay.modules.skins.repricing import reprice_rows

pytestmark = pytest.mark.asyncio


def _skin(name: str, **extra: object) -> dict[str, object]:
    return {
        "market_hash_name": name,
        "category": {"name": "Pistols"},
        "stattrak": False,
        "souvenir": False,
        **extra,
    }


async def _slugs(db: AsyncSession) -> dict[str, str]:
    db.expire_all()
    rows = (await db.execute(select(SkinItem.market_hash_name, SkinItem.slug))).all()
    return {name: slug for name, slug in rows}


async def test_names_that_fold_to_one_slug_both_import(db_session: AsyncSession) -> None:
    rows = dedupe(
        rows_from_skins(
            [
                _skin("Desert Eagle | Sunset Storm 壱 (Field-Tested)"),
                _skin("Desert Eagle | Sunset Storm 弐 (Field-Tested)"),
            ]
        )
        + rows_from_file(
            "stickers",
            [
                {"market_hash_name": "Sticker | NiKo | London 2018"},
                {"market_hash_name": "Sticker | niko  | London 2018"},
            ],
        )
    )
    await upsert_items(db_session, rows)
    await db_session.commit()
    slugs = await _slugs(db_session)
    assert len(slugs) == 4
    assert len(set(slugs.values())) == 4
    # A second import keeps every slug where it was.
    await upsert_items(db_session, rows)
    await db_session.commit()
    assert await _slugs(db_session) == slugs


async def test_stub_slug_collision_does_not_abort_the_tick(db_session: AsyncSession) -> None:
    await upsert_items(
        db_session,
        rows_from_file("stickers", [{"market_hash_name": "Sticker | NiKo | London 2018"}]),
    )
    await db_session.commit()
    snapshot = [SnapshotRow(1, "Sticker | niko  | London 2018", 500, True)]
    result = await apply_prices(db_session, aggregate(snapshot), meta=[], at=now())
    await db_session.commit()
    assert result.stubs == 1
    slugs = await _slugs(db_session)
    assert len(set(slugs.values())) == 2


async def test_a_value_that_appears_later_is_written(db_session: AsyncSession) -> None:
    await upsert_items(db_session, rows_from_skins([_skin("P250 | Sand Dune (Field-Tested)")]))
    await db_session.commit()
    later = rows_from_skins(
        [
            _skin(
                "P250 | Sand Dune (Field-Tested)",
                image="https://community.akamai.steamstatic.com/x",
            )
        ]
    )
    assert await upsert_items(db_session, later) == 1
    await db_session.commit()
    db_session.expire_all()
    row = (await db_session.execute(select(SkinItem))).scalar_one()
    assert row.image_url == "https://community.akamai.steamstatic.com/x"


async def test_phaseless_doppler_stub_stays_hidden(db_session: AsyncSession) -> None:
    snapshot = [SnapshotRow(1, "★ Karambit | Doppler (Factory New)", 900000, True)]
    for _ in range(2):  # the stub tick, then an update tick
        await apply_prices(db_session, aggregate(snapshot), meta=[], at=now())
        await db_session.commit()
        snapshot = [SnapshotRow(1, "★ Karambit | Doppler (Factory New)", 890000, True)]
    db_session.expire_all()
    row = (await db_session.execute(select(SkinItem))).scalar_one()
    assert (row.phase, row.active, row.count_auto) == ("", False, 1)


async def test_zero_steam_price_is_stored_as_unknown(db_session: AsyncSession) -> None:
    snapshot = [SnapshotRow(1, "AK-47 | Redline (Field-Tested)", 27867, True)]
    meta = [{"name": "AK-47 | Redline (Field-Tested)", "steam_price": 0, "type": "Rifles"}]
    await apply_prices(db_session, aggregate(snapshot), meta=meta, at=now())
    await db_session.commit()
    db_session.expire_all()
    assert (await db_session.execute(select(SkinItem))).scalar_one().steam_price_units is None


class _Client:
    def __init__(self, rows: list[SnapshotRow]) -> None:
        self.rows = rows

    async def iter_snapshot_rows(self, *, game: str = "csgo"):  # type: ignore[no-untyped-def]
        for row in self.rows:
            yield row

    async def prices(self, *, game: str = "csgo") -> list[dict[str, object]]:
        return []


async def test_a_collapsed_snapshot_is_refused(db_engine) -> None:  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    full = [SnapshotRow(i, f"P250 | Skin {i} (Field-Tested)", 1000 + i, True) for i in range(10)]
    await sync_prices(factory, _Client(full), redis)  # type: ignore[arg-type]
    result = await sync_prices(factory, _Client(full[:2]), redis)  # type: ignore[arg-type]
    assert result.deactivated == 0
    async with factory() as db:
        active = (await db.execute(select(SkinItem).where(SkinItem.active.is_(True)))).all()
    assert len(active) == 10
    await redis.aclose()


@pytest.fixture
def _enabled(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CS2_SKINS_ENABLED", "true")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def _fx() -> None:
    await build_default_service().publish_quote_setting(
        ManualOverride(quote="UZS", use_manual=True, manual_rate=Decimal("12700"), updated_at=None)
    )


def _row(i: int, *, steam: int | None, cost: int) -> SkinItem:
    return SkinItem(
        id=new_id(),
        market_hash_name=f"P250 | D{i} (Field-Tested)",
        phase="",
        slug=f"p250-d{i}",
        category="pistols",
        search_text=f"p250 d{i}",
        min_auto_units=cost,
        count_auto=5,
        steam_price_units=steam,
        active=True,
        cheapest_auto=[{"listing_id": i, "price_units": cost}],
    )


@pytest.mark.usefixtures("_enabled")
async def test_discount_sort_survives_zero_steam_and_pages_negatives(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _fx()
    db_session.add(_row(0, steam=0, cost=5000))
    for i in range(1, 6):
        db_session.add(_row(i, steam=1000, cost=1025))  # negative discounts after margin
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, str | int] = {"sort": "discount", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        r = await integration_client.get("/api/v1/skins/catalog", params=params)
        assert r.status_code == 200, r.text
        body = r.json()
        seen += [i["slug"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert sorted(seen) == sorted(f"p250-d{i}" for i in range(6))
