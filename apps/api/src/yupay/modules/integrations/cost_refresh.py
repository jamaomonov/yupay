"""Pulling one supplier's price for one mapping, and deciding whose it is.

Split out of ``service.py`` when that file passed 900 lines. It sits beside
``price_refresh.py`` on purpose: that module is the **runner** — a session per
mapping, the alerting, the aggregate report — and this one is the per-mapping
logic it drives. Same concern, two altitudes.

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
from yupay.modules.integrations.models import (
    NOVA_STEAM_SENTINEL,
    SkuSupplierMapping,
    SupplierCatalogCache,
    SupplierPriceHistory,
)

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
    only when ``wrote_cost`` is true *and* the SKU had a saved margin, so
    ``price_usd`` was re-derived alongside the cost — see
    ``catalog.admin_service.set_sku_cost_usdt``.
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


@dataclass(frozen=True)
class _RawPrice:
    """One supplier's answer to "what does this mapping cost right now".

    Exactly one of ``amount``/``reason`` matters to the caller: ``reason``
    set means the lookup produced no usable number (network failure,
    catalogue/offer miss, not configured, the NOVA Steam sentinel) and
    nothing else here should be trusted; otherwise ``amount`` is the raw
    upstream value and ``source`` names where it came from.
    """

    amount: object | None
    source: str
    reason: str | None = None


async def _g2b_raw_price(  # noqa: PLR0911 -- discriminated outcome reads clearer than nested branches
    db: AsyncSession, mapping: SkuSupplierMapping
) -> _RawPrice:
    """G2B's price for one mapping.

    Voucher mappings read the catalog cache (populated by the periodic
    sync); game mappings call ``games_catalogue`` live and match on the
    denom name. Carved out of :func:`refresh_sku_cost_for_mapping` verbatim
    so NOVA could get a sibling without turning that function into one long
    per-supplier branch — the behaviour is unchanged from before the
    dispatch existed.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

    fulfiller = REGISTRY.get("g2b")
    if not isinstance(fulfiller, G2bFulfiller) or not fulfiller.available:
        return _RawPrice(amount=None, source="", reason="G2B is not configured")

    try:
        if mapping.kind == "voucher":
            cache_row = (
                await db.execute(
                    select(SupplierCatalogCache).where(
                        SupplierCatalogCache.supplier_slug == "g2b",
                        SupplierCatalogCache.kind == "voucher",
                        SupplierCatalogCache.external_id == mapping.external_product_id,
                    )
                )
            ).scalar_one_or_none()
            if cache_row is None:
                return _RawPrice(
                    amount=None,
                    source="",
                    reason="ваучер не найден в кэше — синхронизируйте каталог",
                )
            return _RawPrice(
                amount=cache_row.raw.get("unit_price"),
                source="supplier_catalog_cache.unit_price",
            )
        # game
        denom_name = (mapping.external_variant_id or "").strip()
        if not denom_name:
            return _RawPrice(amount=None, source="", reason="у маппинга не указан catalogue_name")
        client = fulfiller._client()
        rows = await client.games_catalogue(mapping.external_product_id)
        match = next(
            (r for r in rows if str(r.get("name") or "").strip() == denom_name),
            None,
        )
        if match is None:
            return _RawPrice(
                amount=None,
                source="",
                reason=f"denom «{denom_name}» не найден в каталоге G2B",
            )
        return _RawPrice(amount=match.get("amount"), source="g2b.games_catalogue.amount")
    except Exception as exc:  # noqa: BLE001 -- best effort
        return _RawPrice(amount=None, source="", reason=f"ошибка обращения к G2B: {exc!s}"[:200])


async def _nova_raw_price(  # noqa: PLR0911 -- one refusal per thing that can be wrong, each with its own operator-facing reason
    mapping: SkuSupplierMapping,
    *,
    offers_cache: dict[str, dict[str, Any]] | None,
) -> _RawPrice:
    """NOVA's price for one mapping: ``GET /topups/offers`` for the
    mapping's category (``external_product_id``), matched on the offer id
    (``external_variant_id``), reading ``price_usd`` off the match.

    Steam (:data:`NOVA_STEAM_SENTINEL`) has no catalogue price to look up —
    its cost is a share of the face value the customer picks at checkout,
    not a catalogue number (ADR-0082 §4) — so it is reported as a reason
    before any network call, and the caller must write nothing for it, not
    even history.

    ``offers_cache``, when given, is checked for the mapping's
    ``external_product_id`` before calling NOVA at all — a caller
    refreshing many SKUs of the same category (a whole brand) fetches the
    category once and passes the same map to every one of them. Building
    that cache is the caller's job (the scheduler); this function only
    reads it.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.nova import NovaFulfiller

    category_id = mapping.external_product_id.strip()
    if category_id == NOVA_STEAM_SENTINEL:
        return _RawPrice(
            amount=None,
            source="",
            reason=(
                "у Steam-пополнения NOVA нет каталожной цены — стоимость зависит "
                "от суммы, которую выбирает покупатель"
            ),
        )
    offer_id = (mapping.external_variant_id or "").strip()
    if not offer_id:
        return _RawPrice(amount=None, source="", reason="у маппинга не указан offer_id")

    fulfiller = REGISTRY.get("nova")
    if not isinstance(fulfiller, NovaFulfiller) or not fulfiller.available:
        return _RawPrice(amount=None, source="", reason="NOVA is not configured")

    try:
        body = (
            offers_cache[category_id]
            if offers_cache is not None and category_id in offers_cache
            else await fulfiller._client().get_offers(category_id)
        )
        offers = [o for o in (body.get("offers") or []) if isinstance(o, dict)]
        matches = [o for o in offers if str(o.get("offer_id") or "").strip() == offer_id]
        if not matches:
            return _RawPrice(
                amount=None,
                source="",
                reason=f"offer «{offer_id}» не найден в каталоге NOVA",
            )
        if len(matches) > 1:
            # Collected rather than `next(...)`, for the reason the mapping seed
            # states in its own words: an id two offers share is an ambiguity to
            # report, not to resolve by taking whichever the supplier listed
            # first. This function now decides a shelf price, so it is exactly
            # the kind of place that rule was written for.
            names = ", ".join(str(o.get("name")) for o in matches)
            return _RawPrice(
                amount=None,
                source="",
                reason=f"offer «{offer_id}» встречается {len(matches)} раза в каталоге"
                f" NOVA ({names}) — цена неоднозначна, поправьте маппинг",
            )
        return _RawPrice(amount=matches[0].get("price_usd"), source="nova.get_offers.price_usd")
    except Exception as exc:  # noqa: BLE001 -- best effort, mirrors G2B
        return _RawPrice(amount=None, source="", reason=f"ошибка обращения к NOVA: {exc!s}"[:200])


def _route_label(decision: Decision) -> str:
    """How the current route reads in an operator-facing message."""
    primary = decision.primary
    if primary.startswith("supplier:"):
        return primary.removeprefix("supplier:")
    if primary == "inventory" and decision.fallback:
        return decision.fallback.removeprefix("supplier:")
    return primary


def _is_routed_supplier(decision: Decision, supplier_slug: str) -> bool:
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


async def refresh_sku_cost_for_mapping(  # noqa: PLR0911 -- discriminated outcome reads clearer than nested branches
    db: AsyncSession,
    *,
    mapping: SkuSupplierMapping,
    record_history: bool = True,
    nova_offers_cache: dict[str, dict[str, Any]] | None = None,
) -> CostRefreshOutcome:
    """Pull the upstream price for ``mapping`` and persist it.

    Handles ``g2b`` (:func:`_g2b_raw_price`) and ``nova``
    (:func:`_nova_raw_price`); any other supplier is reported through the
    outcome, not raised. Every active mapping that produces a usable price
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
    :func:`_is_routed_supplier`). Every other active mapping records
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

    Returns:
        A :class:`CostRefreshOutcome`. Never raises — every failure mode is
        reported through it. The caller is responsible for committing the
        session.
    """

    from yupay.modules.catalog import admin_service as catalog_svc
    from yupay.modules.integrations.models import SupplierPriceHistory
    from yupay.modules.sourcing import service as sourcing_api

    if mapping.supplier_slug == "g2b":
        lookup = await _g2b_raw_price(db, mapping)
    elif mapping.supplier_slug == "nova":
        lookup = await _nova_raw_price(mapping, offers_cache=nova_offers_cache)
    else:
        return CostRefreshOutcome(
            updated=False,
            reason=f"сбор цен не поддержан для поставщика «{mapping.supplier_slug}»",
        )

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
        routed = _is_routed_supplier(decision, mapping.supplier_slug)
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
            db, sku_id=mapping.sku_id, new_cost=new_cost
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
    )
