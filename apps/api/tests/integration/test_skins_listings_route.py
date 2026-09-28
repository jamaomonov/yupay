"""``GET /skins/{slug}/listings``: live read priced with the margin; a 429
upstream is a 200 with ``degraded: true`` and the snapshot's listing."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.core.ids import new_id
from yupay.core.redis import get_redis
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.quote_settings import ManualOverride
from yupay.modules.skins.models import SkinItem

pytestmark = pytest.mark.asyncio
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skins"
HOST = "https://api.waxpeer.test"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CS2_SKINS_ENABLED", "true")
    monkeypatch.setenv("WAXPEER_API_KEY", "k")
    monkeypatch.setenv("WAXPEER_BASE_URL", f"{HOST}/v1")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def _uzs_manual_rate(integration_client: AsyncClient) -> None:
    """FX from Redis, so ``@respx.mock`` never sees a live provider call."""
    await build_default_service().publish_quote_setting(
        ManualOverride(quote="UZS", use_manual=True, manual_rate=Decimal("12700"), updated_at=None)
    )


@pytest.fixture
async def item(db_session: AsyncSession) -> SkinItem:
    row = SkinItem(
        id=new_id(),
        market_hash_name="AK-47 | Redline (Field-Tested)",
        phase="",
        slug="ak-47-redline-field-tested",
        category="rifles",
        search_text="ak 47 redline field tested",
        min_auto_units=27867,
        count_auto=49,
        active=True,
        cheapest_auto=[{"listing_id": 53857957789, "price_units": 27867}],
    )
    db_session.add(row)
    await db_session.commit()
    await get_redis().delete("skins:wax:breaker")
    return row


@respx.mock
async def test_live_listings_are_priced(integration_client: AsyncClient, item: SkinItem) -> None:
    respx.get(f"{HOST}/v2/search-items-by-name").mock(
        return_value=httpx.Response(200, content=(FIXTURES / "search_v2.json").read_bytes())
    )
    r = await integration_client.get(f"/api/v1/skins/{item.slug}/listings")
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is False
    assert [i["listing_id"] for i in body["items"]] == [53857957789, 53863078495]
    assert body["items"][0]["price_usd"] == "30.37"
    assert body["items"][0]["inspect_url"].startswith("steam://")


@respx.mock
async def test_rate_limited_upstream_is_degraded_200(
    integration_client: AsyncClient, item: SkinItem
) -> None:
    await get_redis().delete(f"skins:listings:{item.slug}", f"skins:listings:{item.slug}:stale")
    respx.get(f"{HOST}/v2/search-items-by-name").mock(
        return_value=httpx.Response(429, json={"success": False, "msg": "Too many"})
    )
    r = await integration_client.get(f"/api/v1/skins/{item.slug}/listings")
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is True
    assert [i["listing_id"] for i in body["items"]] == [53857957789]
