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

**A SKU whose price fails the margin floor is absent for the same reason.**
Nothing floors ``b2b_markup_pct``: the schemas accept ``ge=-999.99`` and 0068
adds no ``CHECK``, deliberately — spec §8.3 makes
``pricing.violates_margin_floor`` the guard instead, and Task 4 will reject an
order below it. A price list that advertised those SKUs anyway would be a
promise the order path breaks *after* the reseller has quoted their own
customer off our number. Two reachable mistakes produce it: ``0.5`` typed for
``5`` (published at 0.5% over cost, then every order refused), and ``-100``,
which makes ``merchant_price`` return ``0.00`` and would publish a **free**
SKU — Ruling 3's outcome reached through the markup instead of the cost. So
the floor is applied here as well, and the catalog and the order path cannot
disagree by construction. Support finds the misconfigured rows through the
``merchant_catalog_below_margin_floor`` warning, one line per request listing
every SKU it dropped.

**A variable-amount SKU is absent too**, and for a structural reason rather
than a pricing one: the customer picks the amount, so ``price_usd`` on the row
is not a price and the cost × markup formula has nothing to work on. The order
path refuses them (``item_unavailable`` / ``variable_amount``), so listing one
would advertise a SKU every order rejects.

Note what is deliberately **not** filtered here, because the difference is the
rule: retail ``active``, brand maintenance and supplier stock all move between
a merchant's poll and their order, so the order path is where a merchant
learns about them and a catalog absence would only be stale in the other
direction. ``variable_amount`` is permanent — it cannot become orderable while
it is set — which is why it belongs in the WHERE clause and they do not.

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

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import raiseload

from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.catalog.service import DEFAULT_LOCALE
from yupay.modules.catalog.unit_sku import is_unit_sku
from yupay.modules.merchants import pricing
from yupay.modules.merchants.machine_schemas import (
    MerchantBrandOut,
    MerchantCatalogOut,
    MerchantFieldOut,
    MerchantProductOut,
    MerchantSkuOut,
)

#: A dollar of a dollar-denominated balance costs a dollar.
_ONE = Decimal("1")

log = get_logger("yupay.merchants.price_list")

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

    Reads ``settings.merchant_margin_floor_pct`` and passes it to
    ``pricing.violates_margin_floor`` — the pricing functions stay pure and
    never read settings themselves.

    Args:
        db: Session. The caller owns the transaction.
        merchant: The authenticated merchant — its ``markup_adjustment_pp`` is
            what makes these prices *this* merchant's rather than anyone's.

    Returns:
        The catalog tree, holding only SKUs this merchant can actually buy at
        the price shown. Empty ``brands`` when nothing qualifies, and no brand
        or product ever comes back without a purchasable SKU under it.
    """
    rows = (
        await db.execute(
            select(Brand.id, Brand.slug, Product.id, Product.slug, Product.required_fields, Sku)
            .join(Product, Product.brand_id == Brand.id)
            .join(Sku, Sku.product_id == Product.id)
            .where(
                Brand.visible_b2b.is_(True),
                Sku.visible_b2b.is_(True),
                # ``effective_cost is None`` means NOT SELLABLE, never free.
                # Excluded in SQL as well as honoured below, so an unpriced SKU
                # never reaches the pricing call at all.
                # A SKU is quotable when its cost is knowable. For the two
                # priced-off-a-column shapes that means the column is set; for
                # a balance loaded in dollars it means the bounds exist, since
                # the cost there is the face value on the request and there is
                # nothing to read from the row (``merchant_amount_price``).
                or_(
                    and_(
                        Sku.variable_amount.is_(False),
                        Sku.cost_usdt.is_not(None),
                    ),
                    and_(
                        Sku.variable_amount.is_(True),
                        Sku.min_amount_usd.is_not(None),
                        Sku.max_amount_usd.is_not(None),
                    ),
                ),
                # A customer-chooses-the-amount SKU (a Steam wallet top-up) has
                # no wholesale price to quote: the B2B formula is cost ×
                # markup, while these price off a guarded FX rate and a margin
                # multiplier, and ``price_usd`` on the row is not a price at
                # all. ``merchants.orders`` refuses them with
                # ``item_unavailable`` / ``variable_amount``, so listing one
                # here would advertise a SKU every order rejects.
                #
                # This is a different kind of filter from the ones deliberately
                # NOT applied here — retail ``active``, brand maintenance,
                # supplier stock. Those are transient states that move between
                # a merchant's poll and their order, which is why the order
                # path is where a merchant learns about them (Ruling 2, and the
                # README says so). ``variable_amount`` is a permanent
                # structural property of the SKU: it can never become
                # orderable while it is set, so withholding it costs a merchant
                # nothing and telling them about it costs them a round trip.
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

    floor_pct = get_settings().merchant_margin_floor_pct
    below_floor: list[str] = []
    # ``dict`` preserves insertion order, so the SQL ORDER BY above is the
    # order the tree comes out in — one sort, with no chance of a second one
    # disagreeing with it.
    brands: dict[str, MerchantBrandOut] = {}
    products: dict[str, MerchantProductOut] = {}
    for brand_id, brand_slug, product_id, product_slug, required_fields, sku in rows:
        markup = pricing.merchant_markup_pct(sku, merchant)
        # One dollar of balance costs one dollar, so an amount SKU publishes
        # the price of a dollar and its floor is checked against one.
        cost = _ONE if sku.variable_amount else pricing.effective_cost(sku)
        if cost is None:  # pragma: no cover - the WHERE clause excludes these
            continue
        unit = pricing.merchant_unit_price(cost, markup)
        # The floor on one unit, which is the quantity this row is priced in.
        # ``merchant_order_total(unit, 1)`` is exactly the old ``merchant_price``
        # for a fixed SKU, so a row that listed before still lists.
        price = pricing.merchant_order_total(unit, 1)
        if pricing.violates_margin_floor(cost, price, floor_pct):
            # Not sellable, so not listed — see the module docstring.
            below_floor.append(sku.sku_code)
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
                required_fields=_fields(required_fields),
                skus=[],
            )
            brands[brand_id].products.append(products[product_id])
        products[product_id].skus.append(_row(sku, unit=unit, price=price))
    if below_floor:
        # One line per request, not one per SKU: a merchant polls this
        # endpoint, so a per-row warning would be thousands of lines a day for
        # a condition that needs one admin edit. ``sku_code`` is our own
        # identifier, never PII, and naming it is the only way to find the row.
        log.warning(
            "merchant_catalog_below_margin_floor",
            sku_codes=below_floor,
            floor_pct=str(floor_pct),
            hint="b2b_markup_pct is below settings.merchant_margin_floor_pct for these "
            "SKUs, so they are withheld from the price list and orders for them would "
            "be rejected; fix the markup in the admin catalog",
        )
    return MerchantCatalogOut(brands=list(brands.values()))


def _fields(raw: list[dict[str, Any]] | None) -> list[MerchantFieldOut]:
    """Trim a product's checkout schema to what a caller needs.

    Reads defensively rather than trusting the column's shape: it is JSONB
    written by the admin form and by the G2B importer, so a row with a missing
    key or a label that is a bare string instead of a locale map is a data
    problem, not a reason for every merchant's catalog to 500.
    """
    out: list[MerchantFieldOut] = []
    for item in raw or []:
        key = item.get("key")
        if not isinstance(key, str) or not key:
            continue
        label = item.get("label")
        placeholder = item.get("placeholder")
        pattern = item.get("pattern")
        out.append(
            MerchantFieldOut(
                key=key,
                type=str(item.get("type") or "text"),
                required=bool(item.get("required", True)),
                label={k: str(v) for k, v in label.items()} if isinstance(label, dict) else {},
                placeholder=(
                    {k: str(v) for k, v in placeholder.items()}
                    if isinstance(placeholder, dict)
                    else {}
                ),
                pattern=pattern if isinstance(pattern, str) else None,
            )
        )
    return out


def _row(sku: Sku, *, unit: Decimal, price: Decimal) -> MerchantSkuOut:
    """One catalog row, in whichever of the three shapes this SKU is.

    Exactly one shape's fields carry values and the rest stay ``None``, so a
    client branches on ``kind`` and never on whether a key exists. Decided
    from the same predicates the order path uses (``Sku.variable_amount``,
    ``catalog.unit_sku.is_unit_sku``), so the catalog cannot advertise a shape
    ``quote.resolve_shape`` would refuse.

    The four shared fields are repeated per branch rather than spread from a
    dict: on a contract surface an explicit keyword is checked by the type
    checker, and ``**common`` is not.
    """
    name = sku.denomination or sku.sku_code
    # A variable-amount row's ``price_usd`` is a face-value placeholder, not a
    # price — see the field's own note on the schema.
    retail = None if sku.variable_amount else sku.price_usd
    if sku.variable_amount:
        return MerchantSkuOut(
            sku_id=sku.id,
            sku_code=sku.sku_code,
            name=name,
            kind="amount",
            unit_price_usd=unit,
            unit="usd",
            min_amount_usd=sku.min_amount_usd,
            max_amount_usd=sku.max_amount_usd,
            updated_at=sku.updated_at,
        )
    if is_unit_sku(sku):
        return MerchantSkuOut(
            sku_id=sku.id,
            sku_code=sku.sku_code,
            name=name,
            kind="unit",
            retail_price_usd=retail,
            unit_price_usd=unit,
            unit=sku.amount_unit,
            min_qty=sku.min_qty,
            max_qty=sku.max_qty,
            updated_at=sku.updated_at,
        )
    return MerchantSkuOut(
        sku_id=sku.id,
        sku_code=sku.sku_code,
        name=name,
        kind="fixed",
        price_usd=price,
        retail_price_usd=retail,
        updated_at=sku.updated_at,
    )


__all__ = ["build"]
