"""The wholesale price list a merchant reads from ``GET /merchant/v1/catalog``.

The read model behind the machine API's catalog endpoint (spec §8.4, §9.1):
brands → products → SKUs, filtered to what this merchant may buy and priced
through :mod:`~yupay.modules.merchants.pricing` — never from the retail
``price_usd``.

Reaches into ``catalog.models`` directly, the established pattern for
cross-module row access that ``admin.py``, ``integrations.merchant_feed`` and
``admin.service`` already follow.

## What is visible, and what is not

Effective B2B visibility is ``brand.visible_b2b AND sku.visible_b2b`` — the
two flags migration 0068 added, deliberately separate from retail ``active``
so a brand can be retail-only, merchant-only, both or neither. **``active`` is
not read here**: it is the storefront's switch, and a SKU pulled from the
storefront for a reason that does not apply B2B (a landing page being
rewritten, a seasonal hide) must not silently vanish from a reseller's
integration. Products carry no B2B flag of their own, by design — the levers
are the brand and the SKU.

A SKU with no ``cost_usdt`` is **absent, not free**: ``pricing.effective_cost``
returns ``None`` for it, which means "not sellable B2B" (spec §8.2), and the
order path rejects it for the same reason. Pricing it from a fallback figure
would either give away margin or look like price-gouging, depending on which
way the fallback happened to be wrong.

Steam-gift SKUs are a v1 non-goal and need no rule of their own: the single
``steam-gift`` SKU is not ``visible_b2b``, so the filter above already
excludes it. ``tests/integration/test_merchant_api_read.py`` pins that rather
than assuming it.

## Query shape

**Three queries, whatever the catalog's size** (AGENTS.md §10): the joined
brand/product/SKU rows, then the brand names and the product names for the
ids that survived the filter. Two deliberate choices keep it there:

- Brand and Product are read as **columns, not entities**. Both configure
  ``lazy="selectin"`` relationships (translations, FAQs, the whole product
  and SKU sets, and for a product its joined brand) which fire on every
  entity load — loading them would drag the entire retail catalog, FAQs
  included, through an endpoint that wants four columns.
- ``Sku`` *is* read as an entity, so ``pricing`` is called with exactly the
  type it declares and no second reading of the formula can creep in. Its one
  eager relationship, ``price_overrides`` (a retail per-currency override,
  irrelevant to a USD wholesale price), is turned off with ``raiseload`` —
  which also makes a future access an immediate error instead of a quiet
  per-row query.

``test_the_catalog_query_count_does_not_scale_with_catalog_size`` measures the
count at two catalog sizes and asserts they are equal, so the guard survives
someone adding a fourth query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import raiseload

from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.catalog.service import DEFAULT_LOCALE
from yupay.modules.merchants import pricing
from yupay.modules.merchants.schemas import (
    MerchantBrandOut,
    MerchantCatalogOut,
    MerchantProductOut,
    MerchantSkuOut,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Row
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.merchants.models import Merchant


def _names(rows: Sequence[Row[tuple[str, str, str]]]) -> dict[str, str]:
    """Collapse ``(owner_id, locale, name)`` rows to one name per owner.

    The same precedence ``catalog.service._pick_translation`` applies — the
    default locale, else whatever translation exists — so a brand named in the
    machine API reads the same as on the storefront. Owners with no
    translation row at all are simply absent, and the caller falls back to the
    slug.

    Args:
        rows: ``(owner_id, locale, name)`` triples, ordered by locale so the
            "else whatever exists" branch is deterministic.

    Returns:
        ``owner_id`` → the chosen name.
    """
    chosen: dict[str, str] = {}
    for owner_id, locale, name in rows:
        if owner_id not in chosen or locale == DEFAULT_LOCALE:
            chosen[owner_id] = name
    return chosen


async def build(db: AsyncSession, *, merchant: Merchant) -> MerchantCatalogOut:
    """The whole B2B price list, priced for one merchant.

    See the module docstring for the visibility rules and the query shape.
    Ordering follows the storefront's (``sort_order``, then the stable slug or
    code), so a merchant mirroring our catalog gets a meaningful and repeatable
    sequence rather than Postgres' physical order.

    Args:
        db: Session. The caller owns the transaction.
        merchant: The authenticated merchant — its ``markup_adjustment_pp`` is
            what makes these prices *this* merchant's rather than anyone's.

    Returns:
        The catalog tree. Empty ``brands`` when nothing is B2B-visible, and no
        brand or product ever comes back without a purchasable SKU under it.
    """
    rows = (
        await db.execute(
            select(Brand.id, Brand.slug, Product.id, Product.slug, Sku)
            .join(Product, Product.brand_id == Brand.id)
            .join(Sku, Sku.product_id == Product.id)
            .where(
                Brand.visible_b2b.is_(True),
                Sku.visible_b2b.is_(True),
                # ``effective_cost is None`` means NOT SELLABLE, never free.
                # Excluded in SQL as well as honoured below, so an unpriced SKU
                # never reaches the pricing call at all.
                Sku.cost_usdt.is_not(None),
            )
            .order_by(
                Brand.sort_order,
                Brand.slug,
                Product.sort_order,
                Product.slug,
                Sku.sort_order,
                Sku.sku_code,
            )
            .options(raiseload(Sku.price_overrides))
        )
    ).all()
    if not rows:
        return MerchantCatalogOut(brands=[])

    brand_names = _names(
        (
            await db.execute(
                select(
                    BrandTranslation.brand_id,
                    BrandTranslation.locale,
                    BrandTranslation.name,
                )
                .where(BrandTranslation.brand_id.in_({row[0] for row in rows}))
                .order_by(BrandTranslation.locale)
            )
        ).all()
    )
    product_names = _names(
        (
            await db.execute(
                select(
                    ProductTranslation.product_id,
                    ProductTranslation.locale,
                    ProductTranslation.name,
                )
                .where(ProductTranslation.product_id.in_({row[2] for row in rows}))
                .order_by(ProductTranslation.locale)
            )
        ).all()
    )

    # ``dict`` preserves insertion order, so the SQL ORDER BY above is the
    # order the tree comes out in — one sort, with no chance of a second one
    # disagreeing with it.
    brands: dict[str, MerchantBrandOut] = {}
    products: dict[str, MerchantProductOut] = {}
    for brand_id, brand_slug, product_id, product_slug, sku in rows:
        cost = pricing.effective_cost(sku)
        if cost is None:  # pragma: no cover - the WHERE clause already excludes these
            continue
        if brand_id not in brands:
            brands[brand_id] = MerchantBrandOut(
                brand_id=brand_id,
                slug=brand_slug,
                name=brand_names.get(brand_id, brand_slug),
                products=[],
            )
        if product_id not in products:
            products[product_id] = MerchantProductOut(
                product_id=product_id,
                slug=product_slug,
                name=product_names.get(product_id, product_slug),
                skus=[],
            )
            brands[brand_id].products.append(products[product_id])
        products[product_id].skus.append(
            MerchantSkuOut(
                sku_id=sku.id,
                sku_code=sku.sku_code,
                name=sku.denomination or sku.sku_code,
                price_usd=pricing.merchant_price(cost, pricing.merchant_markup_pct(sku, merchant)),
                updated_at=sku.updated_at,
            )
        )
    return MerchantCatalogOut(brands=list(brands.values()))


__all__ = ["build"]
