"""Brand-scoped sourcing overview — the read side of the sourcing-by-brand screen.

Split out of ``service.py`` (already 286 lines before this; the query
composition below would have pushed it well past the module's 400-LOC soft
limit) — the same reasoning ``integrations/cost_refresh.py`` was split out
of ``integrations/service.py`` on this same branch.

This endpoint exists so an operator can open one brand and see every active
SKU, what each candidate supplier costs, and where the SKU actually routes
today, to compare and switch in bulk (a later task adds the bulk-switch
endpoint). The correctness rule that governs it: the route reported here
must never diverge from what ``sourcing.resolve_for_sku`` would actually
route an order to. Rather than re-deriving "which supplier wins" with a
second implementation, this module batch-loads the same three inputs
``resolve_for_sku`` reads per SKU — the explicit rule row, the product
kind, and the SKU's mapping rows — and hands them to the exact same pure
functions it uses (``service._resolve_explicit_rule``,
``service._auto_decision``, ``service._pick_auto_mapping_slug``), so there
is exactly one definition of the route, computed once per SKU from
batch-loaded data instead of once per SKU from a query.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import NotFoundError
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.integrations.models import (
    MAPPING_REQUIRED_SUPPLIERS,
    SkuSupplierMapping,
    SupplierPriceHistory,
)
from yupay.modules.sourcing.models import SkuSourcingRule
from yupay.modules.sourcing.schemas import (
    SourcingBrandOverviewOut,
    SourcingBrandSkuOut,
    SourcingBrandSupplierOut,
)
from yupay.modules.sourcing.service import (
    _auto_decision,
    _pick_auto_mapping_slug,
    _resolve_explicit_rule,
)


async def get_brand_overview(db: AsyncSession, brand_slug: str) -> SourcingBrandOverviewOut:
    """Sourcing picture for every active SKU of one brand.

    Five bounded queries regardless of how many SKUs the brand has (up to
    ~35 in practice): the brand id, the SKUs with their product, the
    explicit sourcing rules for those SKUs, every mapping row for those
    SKUs, and the latest ``supplier_price_history`` row per
    (sku, supplier) via ``DISTINCT ON`` (mirrors ``fx.refresh_cycle.
    latest_history_rates`` and ``admin.service.get_refs``, the existing
    "latest row per group" pattern in this codebase). None of the five
    queries are repeated per SKU, so the count does not grow with the
    brand's SKU count.

    Args:
        db: Active session.
        brand_slug: The brand's slug, as in the URL.

    Returns:
        One :class:`SourcingBrandSkuOut` per active SKU of the brand, each
        carrying the live route and a per-candidate-supplier cost
        comparison. Empty ``items`` for a brand with no active SKUs — that
        is a valid state, not a 404.

    Raises:
        NotFoundError: No brand has this slug.
    """
    brand_id = (
        await db.execute(select(Brand.id).where(Brand.slug == brand_slug))
    ).scalar_one_or_none()
    if brand_id is None:
        raise NotFoundError("brand not found")

    # Full ``Product`` entities (not a handful of its columns) — mirrors
    # ``integrations.merchant_feed``'s ``select(Sku, Product, Brand)``, the
    # existing precedent in this codebase for mixing full ORM entities in
    # one select and unpacking rows by tuple position.
    sku_rows = (
        await db.execute(
            select(Sku, Product)
            .join(Product, Product.id == Sku.product_id)
            .where(Product.brand_id == brand_id, Sku.active.is_(True))
            .order_by(Product.sort_order, Product.id, Sku.sort_order, Sku.sku_code)
        )
    ).all()
    if not sku_rows:
        return SourcingBrandOverviewOut(items=[])

    sku_ids = [sku.id for sku, _product in sku_rows]

    rule_rows = (
        (await db.execute(select(SkuSourcingRule).where(SkuSourcingRule.sku_id.in_(sku_ids))))
        .scalars()
        .all()
    )
    rules_by_sku: dict[str, SkuSourcingRule] = {r.sku_id: r for r in rule_rows}

    mapping_rows = (
        (await db.execute(select(SkuSupplierMapping).where(SkuSupplierMapping.sku_id.in_(sku_ids))))
        .scalars()
        .all()
    )
    mappings_by_sku: dict[str, list[SkuSupplierMapping]] = defaultdict(list)
    for mapping in mapping_rows:
        mappings_by_sku[mapping.sku_id].append(mapping)

    # Latest history row per (sku_id, supplier_slug) — Postgres DISTINCT ON,
    # not a loop: same technique as ``fx.refresh_cycle.latest_history_rates``
    # and ``admin.service.get_refs``'s order-line lookup. Scoped to the
    # candidate suppliers up front — cost history for a supplier this
    # endpoint never displays isn't worth reading.
    history_stmt = (
        select(
            SupplierPriceHistory.sku_id,
            SupplierPriceHistory.supplier_slug,
            SupplierPriceHistory.cost_usdt,
            SupplierPriceHistory.captured_at,
        )
        .where(
            SupplierPriceHistory.sku_id.in_(sku_ids),
            SupplierPriceHistory.supplier_slug.in_(MAPPING_REQUIRED_SUPPLIERS),
        )
        .distinct(SupplierPriceHistory.sku_id, SupplierPriceHistory.supplier_slug)
        .order_by(
            SupplierPriceHistory.sku_id,
            SupplierPriceHistory.supplier_slug,
            SupplierPriceHistory.captured_at.desc(),
        )
    )
    history_rows = (await db.execute(history_stmt)).all()
    latest_cost: dict[tuple[str, str], tuple[Decimal, datetime]] = {
        (sku_id, supplier_slug): (cost_usdt, captured_at)
        for sku_id, supplier_slug, cost_usdt, captured_at in history_rows
    }

    candidate_slugs = sorted(MAPPING_REQUIRED_SUPPLIERS)
    items: list[SourcingBrandSkuOut] = []
    for sku, product in sku_rows:
        rule = rules_by_sku.get(sku.id)
        mappings = mappings_by_sku.get(sku.id, [])
        if rule is not None and rule.mode != "auto":
            decision = _resolve_explicit_rule(rule, sku_id=sku.id)
        else:
            mapping_slug = _pick_auto_mapping_slug(mappings)
            decision = _auto_decision(
                kind=product.kind, mapping_slug=mapping_slug, rule_present=rule is not None
            )

        active_by_supplier = {m.supplier_slug: m.is_active for m in mappings}
        suppliers = [
            SourcingBrandSupplierOut(
                supplier_slug=slug,
                has_active_mapping=active_by_supplier.get(slug, False),
                latest_cost_usdt=(
                    str(latest_cost[(sku.id, slug)][0]) if (sku.id, slug) in latest_cost else None
                ),
                captured_at=(
                    latest_cost[(sku.id, slug)][1] if (sku.id, slug) in latest_cost else None
                ),
            )
            for slug in candidate_slugs
        ]

        items.append(
            SourcingBrandSkuOut(
                sku_id=sku.id,
                sku_code=sku.sku_code,
                denomination=sku.denomination,
                product_slug=product.slug,
                price_usd=sku.price_usd,
                cost_usdt=sku.cost_usdt,
                primary=decision.primary,
                rule_present=decision.rule_present,
                suppliers=suppliers,
            )
        )

    return SourcingBrandOverviewOut(items=items)


__all__ = ["get_brand_overview"]
