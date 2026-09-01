"""The Merchant Center feed: what goes to Google, and what must not.

Two things carry the money-risk here and each is pinned: the price that lands
in the feed is the storefront's own resolved price (a per-currency override,
never a second pricing path), and SKUs whose price is a rate rather than a
number (variable amount, quantity-priced) never reach Google at all.
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    Product,
    ProductTranslation,
    Sku,
    SkuPrice,
)
from yupay.modules.integrations.merchant_feed import (
    FeedItem,
    MerchantFeedClient,
    build_feed_items,
    sync_merchant_feed,
)

pytestmark = pytest.mark.asyncio

_API = "https://merchantapi.googleapis.com/products/v1"


async def _seed(db: AsyncSession) -> None:
    category = Category(id=new_id(), slug="games-mf", sort_order=0, active=True)
    db.add(category)
    await db.flush()
    brand = Brand(
        id=new_id(),
        slug="pubg-mf",
        category_id=category.id,
        sort_order=0,
        active=True,
        hero_image_url="https://cdn.yupay.uz/brand_hero/pubg.webp",
        translations=[
            BrandTranslation(
                locale="ru", name="PUBG Mobile", short_description="Пополнение UC за сумы"
            )
        ],
    )
    db.add(brand)
    await db.flush()
    product = Product(
        id=new_id(),
        slug="pubg-uc-mf",
        brand_id=brand.id,
        kind="top_up",
        sort_order=0,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="UC")],
    )
    db.add(product)
    await db.flush()
    db.add_all(
        [
            Sku(
                id=new_id(),
                product_id=product.id,
                sku_code="pubgm-mf-60",
                denomination="60 UC",
                region="WW",
                price_usd=Decimal("1.06"),
                image_url="https://cdn.yupay.uz/sku_image/60uc.png",
                sort_order=0,
                active=True,
                price_overrides=[SkuPrice(currency="UZS", price=Decimal("13500"))],
            ),
            # Variable-amount SKU: has a rate, not a price — must be skipped.
            Sku(
                id=new_id(),
                product_id=product.id,
                sku_code="pubgm-mf-variable",
                denomination=None,
                region="WW",
                price_usd=Decimal("1"),
                sort_order=1,
                active=True,
                variable_amount=True,
                min_amount_usd=Decimal("1"),
                max_amount_usd=Decimal("100"),
                rate_multiplier=Decimal("1"),
            ),
            # No image anywhere would be refused by Merchant Center — but the
            # brand hero backstops it, so this one goes through with the hero.
            Sku(
                id=new_id(),
                product_id=product.id,
                sku_code="pubgm-mf-325",
                denomination="325 UC",
                region="WW",
                price_usd=Decimal("5.40"),
                sort_order=2,
                active=True,
                price_overrides=[SkuPrice(currency="UZS", price=Decimal("68000"))],
            ),
            # Deactivated: never fed.
            Sku(
                id=new_id(),
                product_id=product.id,
                sku_code="pubgm-mf-off",
                denomination="985 UC",
                region="WW",
                price_usd=Decimal("16.20"),
                sort_order=3,
                active=False,
                price_overrides=[SkuPrice(currency="UZS", price=Decimal("200000"))],
            ),
        ]
    )
    await db.flush()


async def test_feed_items_mirror_the_storefront_price_and_skip_the_unpriceable(
    db_session: AsyncSession,
) -> None:
    await _seed(db_session)

    items, skipped = await build_feed_items(db_session, base_url="https://yupay.uz/")
    ours = {i.offer_id: i for i in items if i.offer_id.startswith("pubgm-mf-")}

    assert set(ours) == {"pubgm-mf-60", "pubgm-mf-325"}
    assert skipped >= 1  # at least the variable-amount SKU

    sixty = ours["pubgm-mf-60"]
    assert sixty.title == "PUBG Mobile — 60 UC"
    assert sixty.price_micros == 13_500_000_000  # 13 500 UZS, exactly the override
    assert sixty.image_link == "https://cdn.yupay.uz/sku_image/60uc.png"
    assert sixty.link == "https://yupay.uz/store/pubg-mf"
    assert sixty.in_stock is True

    payload = ours["pubgm-mf-325"].to_product_input()
    assert payload["contentLanguage"] == "ru"
    assert payload["feedLabel"] == "UZ"
    attrs = payload["productAttributes"]
    assert attrs["availability"] == "IN_STOCK"
    assert attrs["price"] == {"amountMicros": "68000000000", "currencyCode": "UZS"}
    assert attrs["identifierExists"] is False
    assert attrs["brand"] == "PUBG Mobile"
    assert attrs["imageLink"] == "https://cdn.yupay.uz/brand_hero/pubg.webp"


@respx.mock
async def test_sync_upserts_desired_and_deletes_stale(db_session: AsyncSession) -> None:
    await _seed(db_session)

    inserted: list[str] = []

    def capture_insert(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        inserted.append(body["offerId"])
        assert request.url.params["dataSource"] == "accounts/58/dataSources/107"
        return httpx.Response(200, json={"name": "x"})

    respx.post(f"{_API}/accounts/58/productInputs:insert").mock(side_effect=capture_insert)
    # The account still lists a SKU we no longer sell → it must be deleted.
    respx.get(f"{_API}/accounts/58/products").mock(
        return_value=httpx.Response(
            200,
            json={"products": [{"offerId": "pubgm-mf-60"}, {"offerId": "pubgm-mf-stale"}]},
        )
    )
    deleted = respx.delete(f"{_API}/accounts/58/productInputs/ru~UZ~pubgm-mf-stale").mock(
        return_value=httpx.Response(200, json={})
    )

    async def token() -> str:
        return "test-token"

    client = MerchantFeedClient(account_id="58", data_source_id="107", token_provider=token)
    report = await sync_merchant_feed(db_session, client=client, base_url="https://yupay.uz")
    await client.aclose()

    assert "pubgm-mf-60" in inserted
    assert "pubgm-mf-325" in inserted
    assert "pubgm-mf-off" not in inserted
    assert deleted.called
    assert report.deleted == 1
    assert report.errors == 0
    assert report.upserted == report.desired


@respx.mock
async def test_one_refused_product_does_not_strand_the_rest(db_session: AsyncSession) -> None:
    await _seed(db_session)

    calls = {"n": 0}

    def flaky_insert(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(400, json={"error": {"message": "policy"}})
        return httpx.Response(200, json={"name": "x"})

    respx.post(f"{_API}/accounts/58/productInputs:insert").mock(side_effect=flaky_insert)
    respx.get(f"{_API}/accounts/58/products").mock(
        return_value=httpx.Response(200, json={"products": []})
    )

    async def token() -> str:
        return "test-token"

    client = MerchantFeedClient(account_id="58", data_source_id="107", token_provider=token)
    report = await sync_merchant_feed(db_session, client=client, base_url="https://yupay.uz")
    await client.aclose()

    assert report.errors == 1
    assert report.upserted == report.desired - 1


async def test_deleting_the_already_gone_is_success() -> None:
    with respx.mock:
        respx.delete(f"{_API}/accounts/58/productInputs/ru~UZ~ghost").mock(
            return_value=httpx.Response(404, json={})
        )

        async def token() -> str:
            return "t"

        client = MerchantFeedClient(account_id="58", data_source_id="107", token_provider=token)
        await client.delete("ghost")  # must not raise
        await client.aclose()


def test_feed_item_truncates_title_to_merchant_limit() -> None:
    item = FeedItem(
        offer_id="x",
        title="A" * 200,
        description="d",
        link="https://yupay.uz/store/x",
        image_link="https://cdn.yupay.uz/i.png",
        price_micros=1_000_000,
        in_stock=True,
        brand="B",
    )
    assert len(item.to_product_input()["productAttributes"]["title"]) == 150
