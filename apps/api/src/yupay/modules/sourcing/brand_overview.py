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

from yupay.core.errors import NotFoundError, ValidationError
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
    Decision,
    _auto_decision,
    _pick_auto_mapping_slug,
    _resolve_explicit_rule,
)

#: Per-brand cap on the SKUs this endpoint returns — mirrors
#: ``service.list_rules``'s ``min(limit, 500)``. No brand is anywhere near
#: this in practice (~35 active SKUs is the largest today), so the cap is a
#: backstop rather than a real pagination need: a brand beyond it gets a
#: silently truncated list (the first ``MAX_BRAND_OVERVIEW_SKUS`` active SKUs
#: in the query's own stable order — product sort order, then SKU sort
#: order/code) instead of an endpoint that reads an unbounded number of rows
#: into memory and 500s or times out the page an operator opens to fix
#: routing.
MAX_BRAND_OVERVIEW_SKUS = 500


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
        is a valid state, not a 404. Capped at :data:`MAX_BRAND_OVERVIEW_SKUS`
        (500) active SKUs, in the query's own stable order (product sort
        order, then SKU sort order/code) — a brand beyond that count gets a
        silently truncated list rather than an error; no brand today is
        anywhere near the cap.

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
            .limit(MAX_BRAND_OVERVIEW_SKUS)
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

    # The comparison list's candidate set: the fixed suppliers that always
    # appear (so a supplier the brand has never mapped still shows up as a
    # switch target, ``has_active_mapping=False``, no cost) *union* every
    # supplier that actually has a mapping row among the SKUs being
    # returned *union* every supplier named by a ``force_supplier`` rule
    # among those SKUs. The fixed half alone can omit a supplier that is the
    # SKU's live route right now, on either of ``primary``'s two sources:
    # a mapping onto a supplier outside ``MAPPING_REQUIRED_SUPPLIERS``
    # (waxpeer, say) still wins ``_pick_auto_mapping_slug`` when it is the
    # oldest active, non-reserve mapping — and an explicit ``force_supplier``
    # rule names *any* slug via ``_resolve_explicit_rule``, mapping required
    # or not (``set_rule`` only demands a mapping row when the slug is in
    # ``MAPPING_REQUIRED_SUPPLIERS``; waxpeer needs none). Either path can
    # make ``primary`` name a supplier the fixed-plus-mapped union would
    # have missed, and the reported ``primary`` must always name a supplier
    # present in this same list. Both unions cost no extra query —
    # ``mapping_rows`` and ``rule_rows`` are already loaded above. Sorted
    # for a stable, deterministic order across requests (not insertion
    # order, which would vary with how mappings/rules were created).
    forced_slugs = {
        r.supplier_slug for r in rule_rows if r.mode == "force_supplier" and r.supplier_slug
    }
    candidate_slugs = sorted(
        MAPPING_REQUIRED_SUPPLIERS | {m.supplier_slug for m in mapping_rows} | forced_slugs
    )

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
            SupplierPriceHistory.supplier_slug.in_(candidate_slugs),
        )
        .distinct(SupplierPriceHistory.sku_id, SupplierPriceHistory.supplier_slug)
        .order_by(
            SupplierPriceHistory.sku_id,
            SupplierPriceHistory.supplier_slug,
            SupplierPriceHistory.captured_at.desc(),
            # Tie-break for two rows with the same captured_at on one
            # (sku_id, supplier_slug) — otherwise DISTINCT ON picks whichever
            # one Postgres happens to scan first, arbitrarily and
            # non-reproducibly. Row id descending just needs to be total and
            # deterministic, not meaningful — see minor 5 of the task-3-fix2
            # review.
            SupplierPriceHistory.id.desc(),
        )
    )
    history_rows = (await db.execute(history_stmt)).all()
    latest_cost: dict[tuple[str, str], tuple[Decimal, datetime]] = {
        (sku_id, supplier_slug): (cost_usdt, captured_at)
        for sku_id, supplier_slug, cost_usdt, captured_at in history_rows
    }
    items: list[SourcingBrandSkuOut] = []
    for sku, product in sku_rows:
        rule = rules_by_sku.get(sku.id)
        mappings = mappings_by_sku.get(sku.id, [])
        if rule is not None and rule.mode != "auto":
            try:
                decision = _resolve_explicit_rule(rule, sku_id=sku.id)
            except ValidationError:
                # A malformed row — ``mode="force_supplier"`` with an empty
                # ``supplier_slug`` — that ``set_rule`` itself would refuse to
                # write, but a direct SQL statement, a seed, or a migration
                # can still produce (``sku_sourcing_rules`` has no DB-level
                # check tying the two columns together). This is the screen
                # an operator opens to *fix* routing, so one broken row must
                # not 400 the other ~34: report it with a route the UI can
                # render as broken instead of raising out of the loop.
                decision = Decision(
                    primary="invalid", fallback=None, strict=True, rule_present=True
                )
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
