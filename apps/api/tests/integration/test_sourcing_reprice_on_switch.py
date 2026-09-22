"""Changing a route re-prices the SKU onto the supplier it now buys from.

Before this, ``PUT /admin/sourcing/rules/{sku_id}`` wrote the rule and nothing
else. That moved *who is allowed to write* ``Sku.cost_usdt`` — only the routed
supplier may (ADR-0083 Decision 1) — without moving the cost itself, so the
column kept the previous supplier's number: the old route had lost the right
to update it and the new one had not yet used it. Margin, B2B markup and the
sourcing screen's "current" column all read that stale figure until the hourly
tick, and forever when the new route has no automatic price collection at all.

Every test here drives NOVA gift-card mappings, whose cost lookup reads
``supplier_catalog_cache`` and never the network — so what is under test is
the re-pricing, not a mocked HTTP call.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.integrations.models import SkuSupplierMapping, SupplierCatalogCache
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
CATEGORY_ID = "roblox_global"
CARD_ID = "100_robux"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _admin_headers(client: AsyncClient, db: AsyncSession, tg_id: int) -> dict[str, str]:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    resp = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _seed_sku(
    db: AsyncSession,
    *,
    slug: str,
    cost: str,
    price: str,
    margin: str = "20",
    supplier: str = "nova",
) -> str:
    """One voucher SKU with a cost basis, a margin, and one active mapping.

    The margin is what makes a cost move visible in ``price_usd`` at all —
    ``set_sku_cost_usdt`` only re-derives a price when one is on file.
    """
    category = Category(
        id=new_id(),
        slug=f"cat-{slug}",
        sort_order=1,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=slug)],
    )
    brand = Brand(
        id=new_id(),
        category_id=category.id,
        slug=f"brand-{slug}",
        sort_order=1,
        active=True,
        translations=[BrandTranslation(locale="ru", name=slug)],
    )
    product = Product(
        id=new_id(),
        brand_id=brand.id,
        slug=f"product-{slug}",
        kind="voucher",
        sort_order=1,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name=slug)],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sku-{slug}",
        denomination="100",
        region="GLOBAL",
        price_usd=Decimal(price),
        cost_usdt=Decimal(cost),
        margin_percent=Decimal(margin),
        sort_order=1,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.flush()
    db.add(
        SkuSupplierMapping(
            sku_id=sku.id,
            supplier_slug=supplier,
            kind="voucher",
            external_product_id=CATEGORY_ID,
            external_variant_id=CARD_ID,
            quantity=1,
            extra={},
            is_active=True,
        )
    )
    await db.commit()
    return sku.id


async def _cache_card(db: AsyncSession, price: str) -> None:
    """The catalogue row ``_nova_giftcard_price`` reads instead of the API."""
    db.add(
        SupplierCatalogCache(
            supplier_slug="nova",
            kind="voucher_denom",
            external_id=CARD_ID,
            parent_external_id=CATEGORY_ID,
            title="100 Robux",
            price_usdt=Decimal(price),
            raw={},
        )
    )
    await db.commit()


async def _switch(
    client: AsyncClient, headers: dict[str, str], sku_id: str, supplier: str
) -> dict[str, object]:
    resp = await client.put(
        f"/api/v1/admin/sourcing/rules/{sku_id}",
        json={"mode": "force_supplier", "supplier_slug": supplier},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, object] = resp.json()
    return body


async def test_a_cheaper_supplier_widens_the_margin_and_leaves_the_price(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """«Оставить цену, забрать экономию» — the point of most switches.

    ``allow_price_drop=False`` is what makes this different from saving a
    mapping by hand, where the operator is correcting the mapping itself and
    a lower price follows the lower cost.
    """
    headers = await _admin_headers(integration_client, db_session, tg_id=9301)
    sku_id = await _seed_sku(db_session, slug="cheaper", cost="2.00", price="2.40")
    await _cache_card(db_session, "1.50")

    body = await _switch(integration_client, headers, sku_id, "nova")

    cost_sync = body["cost_sync"]
    assert isinstance(cost_sync, dict)
    assert cost_sync["updated"] is True
    assert cost_sync["new_cost"] == "1.500000"
    assert cost_sync["price_drop_blocked"] is True

    db_session.expire_all()
    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("1.50")
    assert sku.price_usd == Decimal("2.40"), "the shelf price must not follow the cost down"


async def test_a_dearer_supplier_raises_the_price_off_the_new_cost(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The other half of the ratchet, and the owner's explicit call.

    Selling below cost until the next hourly tick is the alternative, so the
    price is re-derived from the new cost plus the SKU's own margin — here
    1.50 at 20% is 1.80.
    """
    headers = await _admin_headers(integration_client, db_session, tg_id=9302)
    sku_id = await _seed_sku(db_session, slug="dearer", cost="1.00", price="1.20")
    await _cache_card(db_session, "1.50")

    body = await _switch(integration_client, headers, sku_id, "nova")

    cost_sync = body["cost_sync"]
    assert isinstance(cost_sync, dict)
    assert cost_sync["updated"] is True
    assert cost_sync["new_price"] == "1.80"
    assert cost_sync["price_drop_blocked"] is False

    db_session.expire_all()
    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("1.50")
    assert sku.price_usd == Decimal("1.80")


async def test_a_supplier_that_reports_no_prices_says_so_and_changes_nothing(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Waxpeer has no ``cost_lookup``, so nothing will ever re-price this SKU.

    Blanking the cost would be worse than leaving it — a NULL breaks margin
    and every B2B price derived from it — so the stale figure stays and the
    operator is told, in the response, that it is now theirs to maintain.
    """
    headers = await _admin_headers(integration_client, db_session, tg_id=9303)
    sku_id = await _seed_sku(
        db_session, slug="unpriced", cost="2.00", price="2.40", supplier="waxpeer"
    )

    body = await _switch(integration_client, headers, sku_id, "waxpeer")

    cost_sync = body["cost_sync"]
    assert isinstance(cost_sync, dict)
    assert cost_sync["updated"] is False
    assert "waxpeer" in str(cost_sync["reason"])

    db_session.expire_all()
    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("2.00")
    assert sku.price_usd == Decimal("2.40")


async def test_an_unsynced_catalogue_still_switches_the_route(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The rule is the operator's decision and it stands on its own.

    With no cache row there is no price to move to, and that must come back
    as a reason rather than a 5xx that leaves the operator unsure whether the
    route changed at all.
    """
    headers = await _admin_headers(integration_client, db_session, tg_id=9304)
    sku_id = await _seed_sku(db_session, slug="unsynced", cost="2.00", price="2.40")

    body = await _switch(integration_client, headers, sku_id, "nova")

    assert body["supplier_slug"] == "nova"
    cost_sync = body["cost_sync"]
    assert isinstance(cost_sync, dict)
    assert cost_sync["updated"] is False
    assert cost_sync["reason"]

    db_session.expire_all()
    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("2.00")


async def test_a_bulk_switch_re_prices_every_sku_it_actually_wrote(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """And only those: a failed rule write routed nothing, so a cost move
    reported against it would be a lie."""
    headers = await _admin_headers(integration_client, db_session, tg_id=9305)
    ok_id = await _seed_sku(db_session, slug="bulk-ok", cost="2.00", price="2.40")
    # No mapping to nova at all, so ``set_rule`` refuses this one by name.
    unmapped_id = await _seed_sku(
        db_session, slug="bulk-bad", cost="2.00", price="2.40", supplier="waxpeer"
    )
    await _cache_card(db_session, "1.50")

    resp = await integration_client.put(
        "/api/v1/admin/sourcing/rules:bulk",
        json={
            "sku_ids": [ok_id, unmapped_id],
            "mode": "force_supplier",
            "supplier_slug": "nova",
        },
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    by_id = {item["sku_id"]: item for item in resp.json()["items"]}
    assert by_id[ok_id]["ok"] is True
    assert by_id[ok_id]["cost_sync"]["new_cost"] == "1.500000"
    assert by_id[unmapped_id]["ok"] is False
    assert by_id[unmapped_id]["cost_sync"] is None
