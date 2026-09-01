"""Push the sellable catalogue into Google Merchant Center.

Free listings and the price badge under an image in Google Images come from
the merchant feed, not from crawling: JSON-LD on the brand pages nudges the
crawler, this module states the facts. Every active fixed-price SKU becomes
one Merchant API product (``offerId = sku_code``); a delisted or deactivated
SKU is deleted from the feed on the next sync — the catalog watchdog turning
a SKU off therefore pulls it out of Google automatically.

Variable-amount and quantity-priced SKUs (Telegram Stars) are skipped for
the same reason they are absent from the JSON-LD: they have a rate, not a
price, and a fabricated number would show wrong money in the SERP. SKUs
without any image are skipped too — ``imageLink`` is mandatory and Merchant
Center would only bounce them one by one in diagnostics.

The Merchant API (successor of the Content API) is plain JSON over OAuth:
``POST products/v1/accounts/{a}/productInputs:insert?dataSource=…`` upserts
by offerId within the data source, ``DELETE productInputs/{lang}~{label}~{id}``
removes. The token comes from an injected async provider so the network
client is testable without Google credentials; production wires a
service-account JWT via ``google-auth`` (ADR-0065).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.config import Settings, get_settings
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Brand, Product, Sku

log = get_logger("yupay.integrations.merchant_feed")

_API = "https://merchantapi.googleapis.com/products/v1"
_SCOPE = "https://www.googleapis.com/auth/content"
_CONTENT_LANGUAGE = "ru"
_FEED_LABEL = "UZ"
_CURRENCY = "UZS"

TokenProvider = Callable[[], Awaitable[str]]


@dataclass(frozen=True)
class FeedItem:
    """One SKU as the Merchant API wants it."""

    offer_id: str
    title: str
    description: str
    link: str
    image_link: str
    price_micros: int
    in_stock: bool
    brand: str

    def to_product_input(self) -> dict[str, Any]:
        return {
            "offerId": self.offer_id,
            "contentLanguage": _CONTENT_LANGUAGE,
            "feedLabel": _FEED_LABEL,
            "productAttributes": {
                "title": self.title[:150],
                "description": self.description[:5000],
                "link": self.link,
                "imageLink": self.image_link,
                "availability": "IN_STOCK" if self.in_stock else "OUT_OF_STOCK",
                "brand": self.brand[:70],
                "price": {"amountMicros": str(self.price_micros), "currencyCode": _CURRENCY},
                "condition": "NEW",
                # Digital goods carry no GTIN/MPN; without this flag Merchant
                # Center holds every item in "pending identifiers" forever.
                "identifierExists": False,
            },
        }


@dataclass(frozen=True)
class FeedSyncReport:
    """One sync's outcome, for the scheduler log line."""

    desired: int = 0
    upserted: int = 0
    deleted: int = 0
    skipped: int = 0
    errors: int = 0


def _title(brand_name: str, product_name: str, denomination: str | None) -> str:
    """«PUBG Mobile — 1800 UC»; the product name fills in for label-less SKUs."""
    return f"{brand_name} — {denomination or product_name}"


async def build_feed_items(db: AsyncSession, *, base_url: str) -> tuple[list[FeedItem], int]:
    """Every active fixed-price SKU as a :class:`FeedItem`.

    Prices resolve exactly the way the storefront's catalog API resolves them
    (per-currency override first, then FX), so the number Google shows is the
    number the customer pays. An FX outage prices nothing wrongly — the SKU
    is skipped this tick and returns on the next.

    Returns:
        ``(items, skipped)`` — skipped counts SKUs with no usable price or
        image, so the log can say the feed is partial rather than hiding it.
    """
    from yupay.modules.catalog.service import _resolve_fixed_price
    from yupay.modules.fx.factory import build_default_service

    fx = build_default_service()
    rows = (
        await db.execute(
            select(Sku, Product, Brand)
            .join(Product, Product.id == Sku.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .where(Sku.active.is_(True), Product.active.is_(True), Brand.active.is_(True))
            .options(selectinload(Sku.price_overrides))
            .order_by(Sku.sku_code)
        )
    ).all()

    base = base_url.rstrip("/")
    items: list[FeedItem] = []
    skipped = 0
    for sku, product, brand in rows:
        if sku.variable_amount or sku.min_qty is not None:
            skipped += 1
            continue
        image = sku.image_url or product.image_url or brand.hero_image_url
        if not image:
            skipped += 1
            continue
        price = await _resolve_fixed_price(sku, _CURRENCY, fx)
        if price is None or Decimal(price.amount) <= 0:
            skipped += 1
            continue
        brand_name = _brand_display_name(brand)
        items.append(
            FeedItem(
                offer_id=sku.sku_code,
                title=_title(brand_name, _product_display_name(product), sku.denomination),
                description=_description(brand, product)
                or _title(brand_name, _product_display_name(product), sku.denomination),
                link=f"{base}/store/{brand.slug}",
                image_link=image,
                price_micros=int(Decimal(price.amount).quantize(Decimal("1")) * 1_000_000),
                in_stock=sku.in_stock,
                brand=brand_name,
            )
        )
    return items, skipped


def _brand_display_name(brand: Brand) -> str:
    for tr in brand.translations:
        if tr.locale == _CONTENT_LANGUAGE and tr.name:
            return tr.name
    return brand.slug


def _product_display_name(product: Product) -> str:
    for tr in product.translations:
        if tr.locale == _CONTENT_LANGUAGE and tr.name:
            return tr.name
    return product.slug


def _description(brand: Brand, product: Product) -> str | None:
    for ptr in product.translations:
        if ptr.locale == _CONTENT_LANGUAGE and ptr.short_description:
            return ptr.short_description
    for btr in brand.translations:
        if btr.locale == _CONTENT_LANGUAGE and btr.short_description:
            return btr.short_description
    return None


class MerchantFeedClient:
    """Thin JSON client for the Merchant API's product endpoints.

    ``token_provider`` is injected so tests exercise the wire format with a
    stub token and no Google account; production passes
    :func:`service_account_token_provider`.
    """

    def __init__(
        self,
        *,
        account_id: str,
        data_source_id: str,
        token_provider: TokenProvider,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._account = account_id
        self._data_source = f"accounts/{account_id}/dataSources/{data_source_id}"
        self._token_provider = token_provider
        self._http = http or httpx.AsyncClient(timeout=30)

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._token_provider()}"}

    async def upsert(self, item: FeedItem) -> None:
        resp = await self._http.post(
            f"{_API}/accounts/{self._account}/productInputs:insert",
            params={"dataSource": self._data_source},
            json=item.to_product_input(),
            headers=await self._headers(),
        )
        resp.raise_for_status()

    async def delete(self, offer_id: str) -> None:
        name = f"{_CONTENT_LANGUAGE}~{_FEED_LABEL}~{offer_id}"
        resp = await self._http.delete(
            f"{_API}/accounts/{self._account}/productInputs/{name}",
            params={"dataSource": self._data_source},
            headers=await self._headers(),
        )
        if resp.status_code != 404:  # deleting the already-gone is success
            resp.raise_for_status()

    async def list_offer_ids(self) -> set[str]:
        """Every offerId currently in the account's processed products."""
        ids: set[str] = set()
        token: str | None = None
        while True:
            params: dict[str, str] = {"pageSize": "250"}
            if token:
                params["pageToken"] = token
            resp = await self._http.get(
                f"{_API}/accounts/{self._account}/products",
                params=params,
                headers=await self._headers(),
            )
            resp.raise_for_status()
            payload = resp.json()
            for product in payload.get("products", []):
                offer = product.get("offerId")
                if offer:
                    ids.add(offer)
            token = payload.get("nextPageToken")
            if not token:
                return ids

    async def aclose(self) -> None:
        await self._http.aclose()


def service_account_token_provider(key_file: str) -> TokenProvider:
    """Access tokens from the service-account key at ``key_file``.

    ``google-auth`` refreshes over a blocking transport, so the refresh runs
    in a thread — this code lives in scheduler jobs, but a blocked event loop
    there still stalls every other job on the tick.
    """
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
        key_file, scopes=[_SCOPE]
    )

    async def provide() -> str:
        def refresh_if_needed() -> str:
            if not credentials.valid:
                credentials.refresh(Request())
            token = credentials.token
            assert isinstance(token, str)  # narrowed for mypy; refresh() sets it
            return token

        return await asyncio.to_thread(refresh_if_needed)

    return provide


def build_client(settings: Settings | None = None) -> MerchantFeedClient | None:
    """The production client, or ``None`` when the feed is not configured."""
    s = settings or get_settings()
    if not (
        s.merchant_center_account_id
        and s.merchant_center_data_source_id
        and s.merchant_center_key_file
    ):
        return None
    return MerchantFeedClient(
        account_id=s.merchant_center_account_id,
        data_source_id=s.merchant_center_data_source_id,
        token_provider=service_account_token_provider(s.merchant_center_key_file),
    )


async def sync_merchant_feed(
    db: AsyncSession,
    *,
    client: MerchantFeedClient,
    base_url: str,
) -> FeedSyncReport:
    """One full reconciliation: upsert every sellable SKU, delete the rest.

    Insert with an existing ``offerId`` replaces the product within the data
    source, so upserts need no read-before-write; deletion is driven off the
    account's own processed-product list, which makes the sync self-healing —
    a SKU deactivated while the feed was broken still gets removed on the
    first healthy tick. Per-item failures are counted and logged, never
    raised: one refused product must not strand the other two hundred.
    """
    desired, skipped = await build_feed_items(db, base_url=base_url)
    errors = 0
    upserted = 0
    for item in desired:
        try:
            await client.upsert(item)
            upserted += 1
        except Exception as exc:  # noqa: BLE001 -- count, log, continue
            errors += 1
            log.warning(
                "integrations.merchant_feed.upsert_failed",
                offer_id=item.offer_id,
                error=str(exc)[:200],
            )

    deleted = 0
    try:
        existing = await client.list_offer_ids()
    except Exception as exc:  # noqa: BLE001 -- listing down: skip deletes this tick
        existing = set()
        errors += 1
        log.warning("integrations.merchant_feed.list_failed", error=str(exc)[:200])
    stale = existing - {item.offer_id for item in desired}
    for offer_id in sorted(stale):
        try:
            await client.delete(offer_id)
            deleted += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            log.warning(
                "integrations.merchant_feed.delete_failed",
                offer_id=offer_id,
                error=str(exc)[:200],
            )

    return FeedSyncReport(
        desired=len(desired),
        upserted=upserted,
        deleted=deleted,
        skipped=skipped,
        errors=errors,
    )


__all__ = [
    "FeedItem",
    "FeedSyncReport",
    "MerchantFeedClient",
    "build_client",
    "build_feed_items",
    "service_account_token_provider",
    "sync_merchant_feed",
]
