"""The admin side of smart routing (ADR-0108): its switches, handing SKUs to it,
and the list of what it moved."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.sourcing.models import SkuSourcingRule, SourcingSettings, SourcingSwitchLog

from tests.integration.test_sourcing_bulk_rules_routes import (
    _add_mapping,
    _admin_headers,  # noqa: F401 -- a fixture, used by name
    _seed_brand_with_skus,
)

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/admin/sourcing"


async def test_settings_read_the_default_then_save_a_patch(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],  # noqa: F811
) -> None:
    await db_session.execute(delete(SourcingSettings))
    await db_session.commit()

    r = await integration_client.get(f"{BASE}/settings", headers=_admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["smart_mode"] == "off"

    r = await integration_client.patch(
        f"{BASE}/settings",
        headers=_admin_headers,
        json={"smart_mode": "shadow", "smart_dwell_hours": 12},
    )
    assert r.status_code == 200, r.text
    assert r.json()["smart_mode"] == "shadow"
    assert r.json()["smart_dwell_hours"] == 12

    r = await integration_client.get(f"{BASE}/settings", headers=_admin_headers)
    assert r.json()["smart_mode"] == "shadow"


async def test_managed_pins_each_sku_to_its_route_and_reports_what_it_cannot(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],  # noqa: F811
) -> None:
    routed, unrouted = await _seed_brand_with_skus(db_session, n=2, slug_prefix="smart-managed")
    await _add_mapping(db_session, sku_id=routed, supplier_slug="waxpeer")

    r = await integration_client.put(
        f"{BASE}/rules:managed",
        headers=_admin_headers,
        json={"sku_ids": [routed, unrouted], "managed": True},
    )
    assert r.status_code == 200, r.text
    items = {i["sku_id"]: i for i in r.json()["items"]}
    assert items[routed]["ok"] is True
    assert items[unrouted]["ok"] is False
    assert items[unrouted]["error"]

    rule = await db_session.get(SkuSourcingRule, routed, populate_existing=True)
    assert rule is not None
    assert (rule.mode, rule.supplier_slug, rule.managed) == ("force_supplier", "waxpeer", True)
    assert await db_session.get(SkuSourcingRule, unrouted) is None

    # Pinning keeps the rule and its supplier; only the flag changes.
    r = await integration_client.put(
        f"{BASE}/rules:managed",
        headers=_admin_headers,
        json={"sku_ids": [routed], "managed": False},
    )
    assert r.status_code == 200, r.text
    rule = await db_session.get(SkuSourcingRule, routed, populate_existing=True)
    assert rule is not None
    assert (rule.supplier_slug, rule.managed) == ("waxpeer", False)


async def test_switches_list_newest_first_with_the_sku_label(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],  # noqa: F811
) -> None:
    (sku_id,) = await _seed_brand_with_skus(db_session, n=1, slug_prefix="smart-log")
    db_session.add(
        SourcingSwitchLog(
            id=new_id(),
            sku_id=sku_id,
            from_supplier="g2b",
            to_supplier="nova",
            reason="cheaper",
            applied=True,
        )
    )
    await db_session.commit()

    r = await integration_client.get(f"{BASE}/switches?limit=5", headers=_admin_headers)
    assert r.status_code == 200, r.text
    mine = [i for i in r.json()["items"] if i["sku_id"] == sku_id]
    assert len(mine) == 1
    assert mine[0]["sku_code"] == "smart-log-sku-0"
    assert mine[0]["label"]
    assert (mine[0]["to_supplier"], mine[0]["reason"]) == ("nova", "cheaper")
