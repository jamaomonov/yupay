"""Deciding whose price wins for one mapping, and persisting it.

Split out of ``service.py`` when that file passed 900 lines. It sits beside
``price_refresh.py`` on purpose: that module is the **runner** — a session per
mapping, the alerting, the aggregate report — and this one is the per-mapping
logic it drives. Same concern, two altitudes.

The per-supplier "what does it cost right now" lookups (G2B, NOVA) live in
``cost_lookup.py``, split out from here in turn when this module itself
passed 495 lines — this module dispatches into them by
``mapping.supplier_slug`` and owns everything downstream of the raw price:
who is allowed to write it, and persisting the result.

The rule this module exists to hold: ``Sku.cost_usdt`` is **our** cost basis,
not a fact about a supplier. Retail price derives from it, an order line
freezes it at checkout, and the margin report subtracts it — so exactly one
supplier may write it, the one the SKU actually routes to. Every other active
mapping records history and touches nothing else. Without that, a SKU carrying
two active mappings would have its shelf price flip every hour depending on
which mapping the refresh reached last, and 22 production SKUs carry two today.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.integrations.cost_lookup import (
    _g2b_raw_price,
    _gengine_raw_price,
    _nova_raw_price,
)
from yupay.modules.integrations.models import SkuSupplierMapping, SupplierPriceHistory

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.sourcing.service import Decision

log = get_logger("yupay.integrations.cost_refresh")


@dataclass(frozen=True)
class CostRefreshOutcome:
    """Return type for :func:`refresh_sku_cost_for_mapping`.

    ``updated`` reflects whether ``Sku.cost_usdt`` actually changed value.
    ``wrote_cost`` is the broader fact: whether this call was even *allowed*
    to touch ``Sku.cost_usdt`` — true only when ``mapping`` is the supplier
    the SKU is actually routed to (the routed-supplier rule in
    :func:`refresh_sku_cost_for_mapping`). So four combinations are all
    real: routed with a price move (``wrote_cost=True, updated=True``),
    routed with no move (``wrote_cost=True, updated=False``), not routed
    (``wrote_cost=False, updated=False`` — a history row may still have been
    written, ``Sku.cost_usdt`` never was), and no price at all
    (``wrote_cost=False, updated=False, reason=...``).

    ``reason`` is populated whenever the call produced no price to act on
    (network failure, catalogue/offer miss, not configured, the NOVA Steam
    sentinel, ...) to give the admin UI / scheduler logs something to
    surface. ``old_price``/``new_price``/``margin_percent`` are populated
    only when ``wrote_cost`` is true *and* the SKU had a saved margin *and*
    the re-derived price was actually written, so ``price_usd`` moved
    alongside the cost — see ``catalog.admin_service.set_sku_cost_usdt``.

    ``price_drop_blocked`` is the other half of that same margin/moved
    case: true when a margin was on file, the cost moved *down*, and
    ``allow_price_drop=False`` refused to write the lower candidate price.
    Cost still updates; ``price_usd`` does not. Kept distinct from "no
    margin on file" so the alert built from this outcome can say the price
    was deliberately left alone instead of reading as unrelated silence.
    """

    updated: bool
    wrote_cost: bool = False
    old_cost: Any | None = None
    new_cost: Any | None = None
    source: str | None = None
    reason: str | None = None
    old_price: Any | None = None
    new_price: Any | None = None
    margin_percent: Any | None = None
    price_drop_blocked: bool = False


def _route_label(decision: Decision) -> str:
    """How the current route reads in an operator-facing message."""
    primary = decision.primary
    if primary.startswith("supplier:"):
        return primary.removeprefix("supplier:")
    if primary == "inventory" and decision.fallback:
        return decision.fallback.removeprefix("supplier:")
    return primary


#: Suppliers ``refresh_sku_cost_for_mapping`` can actually pull a live price
#: for — the two branches of its dispatch below. Anything else gets the
#: "сбор цен не поддержан" reason and never reaches ``cost_lookup``. Defined
#: once, as a set the dispatch itself checks (see ``supports_price_collection``),
#: rather than duplicated as a second hardcoded list elsewhere — a SKU
#: force-routed to a supplier outside this set has no live price to call
#: "current", however recently `Sku.cost_usdt` was written by a *previous*
#: routed supplier.
PRICE_COLLECTION_SUPPORTED_SUPPLIERS = frozenset({"g2b", "gengine", "nova"})


def supports_price_collection(supplier_slug: str) -> bool:
    """Whether :func:`refresh_sku_cost_for_mapping` can pull a live price for this supplier.

    Only g2b and nova have a ``cost_lookup`` implementation today; every
    other supplier's mapping is refreshed with a "not supported" reason
    instead of a price (see the dispatch in
    :func:`refresh_sku_cost_for_mapping`). ``sourcing.brand_overview`` reads
    this too, to decide whether a routed supplier's ``cost_source`` can
    honestly be reported as ``"current"`` — a SKU routed to a supplier this
    function refuses has no live number behind it, whatever
    ``Sku.cost_usdt`` happens to hold.

    Args:
        supplier_slug: The supplier to check.

    Returns:
        ``True`` for g2b and nova; ``False`` for everything else.
    """
    return supplier_slug in PRICE_COLLECTION_SUPPORTED_SUPPLIERS


def is_routed_supplier(decision: Decision, supplier_slug: str) -> bool:
    """Whether ``supplier_slug`` is the supplier this SKU actually buys from.

    Matches the two shapes ``sourcing.resolve_for_sku`` answers in:

    - A ``top_up`` SKU, or any SKU carrying an explicit ``force_supplier``
      rule, names the supplier directly: ``decision.primary ==
      "supplier:<slug>"``.
    - A ``voucher`` SKU with no override routes to inventory first by
      kind-default (``decision.primary == "inventory"``); the supplier that
      would actually be charged on a stockout is named in
      ``decision.fallback`` instead, and *that* one owns the cost basis —
      the pre-existing on-save refresh for voucher mappings already relied
      on this being true (one active mapping, always refreshed) before this
      function knew about routing at all, and a second voucher mapping must
      not stop it from being true.

    A ``force_inventory`` rule (``fallback=None``, strict) or the
    ``manual`` route matches no supplier, on purpose: no live supplier
    price is "the" cost basis there either.
    """
    target = f"supplier:{supplier_slug}"
    if decision.primary == target:
        return True
    return decision.primary == "inventory" and decision.fallback == target


async def _last_history_cost(db: AsyncSession, *, sku_id: str, supplier_slug: str) -> Any | None:
    """Most recent ``supplier_price_history.cost_usdt`` for one
    SKU↔supplier pair, or ``None`` if that pair has never been recorded.

    Typed ``Any`` because ``SupplierPriceHistory.cost_usdt`` is itself
    ``Mapped[Any]`` (a ``Numeric`` column) — same reason
    :class:`CostRefreshOutcome`'s cost fields are ``Any | None``.

    The "previous" baseline for a **non-routed** mapping: judged against
    its own last recorded price, never against ``Sku.cost_usdt`` — which
    belongs to whichever supplier is actually routed, a different number
    entirely once two mappings are active on the same SKU.
    """

    return (
        await db.execute(
            select(SupplierPriceHistory.cost_usdt)
            .where(
                SupplierPriceHistory.sku_id == sku_id,
                SupplierPriceHistory.supplier_slug == supplier_slug,
            )
            .order_by(SupplierPriceHistory.captured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _lookup_price(
    db: AsyncSession,
    mapping: SkuSupplierMapping,
    *,
    nova_offers_cache: dict[str, Any] | None,
) -> Any:
    """Ask whichever supplier owns ``mapping`` what it costs right now.

    A function rather than three branches inside
    :func:`refresh_sku_cost_for_mapping`: that one is already at the
    branch ceiling ruff enforces, and the third supplier is exactly the
    point at which "one more elif" stops being the honest shape. Callers
    reach this only after :func:`supports_price_collection` has said yes,
    so the final ``else`` is total rather than a default.
    """
    if mapping.supplier_slug == "g2b":
        return await _g2b_raw_price(db, mapping)
    if mapping.supplier_slug == "gengine":
        return await _gengine_raw_price(db, mapping)
    return await _nova_raw_price(db, mapping, offers_cache=nova_offers_cache)


async def refresh_sku_cost_for_mapping(  # noqa: PLR0911 -- discriminated outcome reads clearer than nested branches
    db: AsyncSession,
    *,
    mapping: SkuSupplierMapping,
    record_history: bool = True,
    nova_offers_cache: dict[str, dict[str, Any]] | None = None,
    allow_price_drop: bool = True,
) -> CostRefreshOutcome:
    """Pull the upstream price for ``mapping`` and persist it.

    Handles ``g2b`` (:func:`_g2b_raw_price`), ``gengine``
    (:func:`_gengine_raw_price`) and ``nova`` (:func:`_nova_raw_price`); any
    other supplier is reported through the outcome, not raised. Every active mapping that produces a usable price
    gets a ``supplier_price_history`` row — that table is the per-supplier
    comparison the admin screen reads, and it is written whoever the
    supplier is.

    ``Sku.cost_usdt`` is different. It is not a fact about a supplier — it
    is **our** cost basis: retail price derives from it
    (``catalog.admin_service.set_sku_cost_usdt`` re-derives ``price_usd``
    from ``margin_percent`` whenever the cost moves), an order line freezes
    it at checkout, and the margin report subtracts it from revenue. If two
    suppliers were both allowed to write it, a SKU's retail price would
    flip between their two numbers every hour, depending on which mapping
    the refresh happened to reach last — not hypothetical: 22 production
    SKUs already carry two active mappings (G2B and NOVA) on this branch.
    So exactly one supplier may write it: the one
    ``sourcing.resolve_for_sku`` says this SKU actually routes to (see
    :func:`is_routed_supplier`). Every other active mapping records
    history and touches nothing else.

    Centralised here (instead of inside the upsert route) so the
    hourly scheduler can reuse the exact same logic without dragging
    HTTP-layer types into a background actor.

    Args:
        db: Active session (caller commits).
        mapping: The mapping to refresh.
        record_history: Whether to persist a ``supplier_price_history`` row
            when the price actually moved since that supplier's own last
            recorded price. ``True`` in every current caller; a hook for a
            future dry-run.
        nova_offers_cache: Pre-fetched ``{category_id: get_offers() body}``
            for NOVA mappings, so a caller refreshing many SKUs of the same
            category (e.g. a whole brand) fetches it once instead of once
            per SKU. Ignored for ``g2b`` mappings. Building the cache is
            the caller's job — this function only reads it.
        allow_price_drop: Forwarded verbatim to
            ``catalog.admin_service.set_sku_cost_usdt`` — whether a
            margin-derived price *lower* than the SKU's current price may
            be written. Defaults to ``True`` (today's behaviour); the
            hourly/on-demand price-refresh runner is the one caller that
            passes ``False`` so an automatic sync never hands a supplier's
            cheaper cost to the customer as a lower shelf price. See that
            function's docstring for the full rule.

    Returns:
        A :class:`CostRefreshOutcome`. Never raises — every failure mode is
        reported through it. The caller is responsible for committing the
        session.
    """

    from yupay.modules.catalog import admin_service as catalog_svc
    from yupay.modules.integrations.models import SupplierPriceHistory

    # Reach into ``sourcing.service`` directly (not ``sourcing.api``): the
    # facade imports ``sourcing.routes`` and its router, which this call has
    # no business loading just to resolve one SKU's route.
    from yupay.modules.sourcing import service as sourcing_api

    if not supports_price_collection(mapping.supplier_slug):
        return CostRefreshOutcome(
            updated=False,
            reason=f"сбор цен не поддержан для поставщика «{mapping.supplier_slug}»",
        )
    lookup = await _lookup_price(db, mapping, nova_offers_cache=nova_offers_cache)

    if lookup.reason is not None:
        return CostRefreshOutcome(updated=False, reason=lookup.reason, source=lookup.source or None)

    raw_amount = lookup.amount
    source = lookup.source
    if raw_amount is None:
        return CostRefreshOutcome(updated=False, reason="поставщик не вернул цену", source=source)
    try:
        new_cost = Decimal(str(raw_amount))
    except (InvalidOperation, ValueError):
        return CostRefreshOutcome(
            updated=False,
            reason=f"непарсимая цена: {raw_amount!r}",
            source=source,
        )
    if new_cost <= 0:
        return CostRefreshOutcome(
            updated=False, reason="цена ≤ 0", source=source, new_cost=str(new_cost)
        )

    # Both of these read the database, and this function is contracted never
    # to raise: the admin's mapping-save route calls it *before* its commit, so
    # an exception here does not merely lose a cost refresh — it 500s the
    # request and rolls back the mapping the operator just created.
    # `resolve_for_sku` can raise on a malformed rule (`force_supplier` with an
    # empty slug is refused by `set_rule` but not by the database), and a
    # history read is a query like any other.
    try:
        decision = await sourcing_api.resolve_for_sku(db, mapping.sku_id)
        routed = is_routed_supplier(decision, mapping.supplier_slug)
        previous_for_supplier = await _last_history_cost(
            db, sku_id=mapping.sku_id, supplier_slug=mapping.supplier_slug
        )
    except Exception as exc:  # noqa: BLE001 -- see above; never raise from here
        return CostRefreshOutcome(
            updated=False,
            reason=f"не удалось определить маршрут SKU: {exc!s}"[:200],
            source=source,
            new_cost=str(new_cost),
        )

    if not routed:
        previous = previous_for_supplier
        moved = previous != new_cost
        if record_history and moved:
            db.add(
                SupplierPriceHistory(
                    id=new_id(),
                    sku_id=mapping.sku_id,
                    supplier_slug=mapping.supplier_slug,
                    kind=mapping.kind,
                    external_product_id=mapping.external_product_id,
                    external_variant_id=mapping.external_variant_id,
                    cost_usdt=new_cost,
                    previous_cost_usdt=previous,
                    source=source,
                )
            )
        return CostRefreshOutcome(
            updated=False,
            wrote_cost=False,
            old_cost=previous,
            new_cost=new_cost,
            source=source,
            # Not silence: the admin's save form shows this line, and "not
            # updated" with no reason reads as a broken sync. What happened is
            # that the price was recorded for comparison and the SKU's own cost
            # was left to the supplier actually filling it.
            reason=(
                "цена записана в историю для сравнения; cost_usdt пишет только "
                f"поставщик, на которого маршрутизирован SKU (сейчас {_route_label(decision)})"
            ),
        )

    try:
        cost_update = await catalog_svc.set_sku_cost_usdt(
            db, sku_id=mapping.sku_id, new_cost=new_cost, allow_price_drop=allow_price_drop
        )
    except Exception as exc:  # noqa: BLE001
        return CostRefreshOutcome(
            updated=False, reason=f"не удалось записать cost_usdt: {exc!s}"[:200]
        )

    # Two different questions, and conflating them is a regression I made once
    # already: "did OUR cost move" decides `updated`, the alert and whether a
    # history row is written at all, and it is about `Sku.cost_usdt`. "What did
    # this supplier last cost" is the history row's own baseline, and it is
    # about this supplier — the two differ exactly when a SKU has just been
    # switched, because the SKU's old cost is then the *other* supplier's
    # number. Writing that as this supplier's previous price would record a
    # move it never made, into the one table built to compare them.
    previous = cost_update.previous_cost
    moved = previous != new_cost
    if record_history and moved:
        db.add(
            SupplierPriceHistory(
                id=new_id(),
                sku_id=mapping.sku_id,
                supplier_slug=mapping.supplier_slug,
                kind=mapping.kind,
                external_product_id=mapping.external_product_id,
                external_variant_id=mapping.external_variant_id,
                cost_usdt=new_cost,
                previous_cost_usdt=previous_for_supplier,
                source=source,
            )
        )

    return CostRefreshOutcome(
        updated=moved,
        wrote_cost=True,
        old_cost=previous,
        new_cost=new_cost,
        source=source,
        old_price=cost_update.previous_price,
        new_price=cost_update.new_price,
        margin_percent=cost_update.margin_percent,
        price_drop_blocked=cost_update.price_drop_blocked,
    )
