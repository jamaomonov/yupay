"""Filters and sorts use the stored sell price the card shows (plan 2, Task 1)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.fulfillment.suppliers.waxpeer_client import SnapshotRow
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.quote_settings import ManualOverride
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.naming import slug_for
from yupay.modules.skins.prices import aggregate, apply_prices
from yupay.modules.skins.pricing import DEFAULT_RULES
from yupay.modules.skins.repricing import reprice_rows

pytestmark = pytest.mark.asyncio
_RATE = Decimal("12700")


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CS2_SKINS_ENABLED", "true")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def _fx() -> None:
    await build_default_service().publish_quote_setting(
        ManualOverride(quote="UZS", use_manual=True, manual_rate=_RATE, updated_at=None)
    )


def _item(name: str, weapon: str, skin: str, ext: str, cost: int, **kw: object) -> SkinItem:
    return SkinItem(
        id=new_id(),
        market_hash_name=name,
        phase="",
        slug=slug_for(name, ""),
        category="rifles",
        weapon=weapon,
        skin=skin,
        exterior=ext,
        search_text=name.lower(),
        min_auto_units=cost,
        count_auto=10,
        active=True,
        cheapest_auto=[{"listing_id": 1, "price_units": cost}],
        **kw,
    )


async def test_price_tick_writes_sell_price_and_discount(db_session: AsyncSession) -> None:
    snap = [SnapshotRow(1, "AK-47 | Redline (Field-Tested)", 27867, True)]
    meta = [{"name": "AK-47 | Redline (Field-Tested)", "steam_price": 43794, "type": "Rifles"}]
    await apply_prices(db_session, aggregate(snap), meta=meta, at=now())
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    row = (await db_session.execute(select(SkinItem))).scalar_one()
    # 1 auto listing -> liquidity +3 pp: 1.80069 + 6 % × 27.867 = 3.47271 -> 31.34
    assert row.sell_price_usd == Decimal("31.34")
    assert row.discount_percent == 28  # (43.794 - 31.34) / 43.794 = 28.4 % -> 28


async def test_uzs_filter_uses_the_sell_price(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _fx()
    db_session.add_all(
        [
            _item("A | One (Field-Tested)", "A", "One", "FT", 9500),  # sells ~ $10.55
            _item("A | Two (Field-Tested)", "A", "Two", "FT", 8000),  # sells ~ $8.93
        ]
    )
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    r = await integration_client.get("/api/v1/skins/catalog", params={"max_uzs": str(10 * _RATE)})
    assert [i["name"] for i in r.json()["items"]] == ["A | Two (Field-Tested)"]


async def test_uzs_filter_without_fx_is_ignored(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yupay.modules.skins import routes

    async def no_rate(_fx: object) -> None:  # what ``_uzs_rate`` returns on an FX outage
        return None

    monkeypatch.setattr(routes, "_uzs_rate", no_rate)
    db_session.add(_item("A | One (Field-Tested)", "A", "One", "FT", 9500))
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    r = await integration_client.get("/api/v1/skins/catalog", params={"max_uzs": "1"})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1


async def test_detail_carries_the_wear_family(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _fx()
    db_session.add_all(
        [
            _item("AK-47 | Redline (Field-Tested)", "AK-47", "Redline", "FT", 27867),
            _item("AK-47 | Redline (Minimal Wear)", "AK-47", "Redline", "MW", 60000),
            _item(
                "StatTrak™ AK-47 | Redline (Field-Tested)",
                "AK-47",
                "Redline",
                "FT",
                80000,
                stattrak=True,
            ),
            _item("AK-47 | Asiimov (Field-Tested)", "AK-47", "Asiimov", "FT", 50000),
        ]
    )
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    body = (await integration_client.get("/api/v1/skins/ak-47-redline-field-tested")).json()
    fam = [(m["exterior"], m["stattrak"]) for m in body["family"]]
    assert fam == [("MW", False), ("FT", False), ("FT", True)]


async def test_rules_put_reprices_every_row(db_session: AsyncSession) -> None:
    db_session.add(_item("A | One (Field-Tested)", "A", "One", "FT", 9500))
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    before = (await db_session.execute(select(SkinItem.sell_price_usd))).scalar_one()
    richer = DEFAULT_RULES.model_copy(update={"expenses_percent": Decimal("20")})
    assert await reprice_rows(db_session, richer) == 1
    await db_session.commit()
    after = (await db_session.execute(select(SkinItem.sell_price_usd))).scalar_one()
    assert after is not None
    assert before is not None
    assert after > before
