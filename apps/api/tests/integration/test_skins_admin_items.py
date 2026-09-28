"""``GET /admin/skins/items``: find an item to override, or list the overridden ones."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.skins.models import SkinItem

from tests.integration.test_skins_admin_pricing import _admin_headers, _env  # noqa: F401

pytestmark = pytest.mark.asyncio


def _item(slug: str, name: str, search: str, count: int, **over: object) -> SkinItem:
    return SkinItem(
        id=new_id(),
        market_hash_name=name,
        phase="",
        slug=slug,
        category="rifles",
        weapon=name.split(" | ", maxsplit=1)[0],
        search_text=search,
        min_auto_units=27867,
        count_auto=count,
        active=True,
        **over,
    )


@pytest.fixture
async def rows(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            _item("ak-redline-ft", "AK-47 | Redline (Field-Tested)", "ak 47 redline ft", 49),
            _item("ak-redline-mw", "AK-47 | Redline (Minimal Wear)", "ak 47 redline mw", 7),
            _item(
                "awp-asiimov-ft",
                "AWP | Asiimov (Field-Tested)",
                "awp asiimov ft",
                30,
                margin_override_pp=Decimal("3.50"),
                sell_price_usd=Decimal("80.00"),
            ),
        ]
    )
    await db_session.commit()


async def test_finds_by_part_of_the_name_most_liquid_first(
    integration_client: AsyncClient, db_session: AsyncSession, rows: None
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=951_001)
    r = await integration_client.get(
        "/api/v1/admin/skins/items", params={"q": "redline"}, headers=headers
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["slug"] for i in items] == ["ak-redline-ft", "ak-redline-mw"]
    assert items[0]["cost_usd"] == "27.867"
    assert items[0]["margin_override_pp"] is None


async def test_lists_only_overridden_items(
    integration_client: AsyncClient, db_session: AsyncSession, rows: None
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=951_002)
    r = await integration_client.get(
        "/api/v1/admin/skins/items", params={"overridden": "true"}, headers=headers
    )
    items = r.json()["items"]
    assert [i["slug"] for i in items] == ["awp-asiimov-ft"]
    assert items[0]["margin_override_pp"] == "3.50"
    assert items[0]["sell_price_usd"] == "80.00"


async def test_clamps_the_page(
    integration_client: AsyncClient, db_session: AsyncSession, rows: None
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=951_003)
    r = await integration_client.get(
        "/api/v1/admin/skins/items", params={"q": "ft", "limit": "1"}, headers=headers
    )
    assert len(r.json()["items"]) == 1
