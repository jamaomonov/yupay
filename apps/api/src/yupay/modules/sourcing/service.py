"""Sourcing service: per-SKU decision rules.

Default behaviour (no row in ``sku_sourcing_rules``) depends on the
product kind, because inventory only makes sense for assets we can
physically stock:

- ``product.kind == 'voucher'`` (gift cards, license keys, anything
  that arrives as a string we can hand to the customer): try the
  in-house warehouse first; fall back to a supplier when stock is
  empty. The fallback target is the cheapest active mapping if any
  exists, else ``DEFAULT_FALLBACK_SUPPLIER`` (which is ``mock`` in
  dev and ``StubFulfiller`` in prod → task ends ``failed``).
- ``product.kind == 'top_up'`` (game balance, MLBB diamonds, PUBG
  UC): there's nothing to stock — the supplier credits the player's
  account directly. If the SKU has an active supplier mapping the
  route is the supplier; otherwise it lands in the admin manual
  queue (no inventory attempts, no mock fallback).

Explicit ``sku_sourcing_rules`` rows still override everything — the
kind-aware defaults are a sane starting point, not a constraint.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.sourcing.models import SkuSourcingRule

if TYPE_CHECKING:
    # Type-only — a real import here would close the same cycle the lazy
    # imports below avoid (see the comment on ``_resolve_auto``).
    from yupay.modules.integrations.models import SkuSupplierMapping

Mode = Literal["auto", "force_inventory", "force_supplier", "manual"]
DEFAULT_FALLBACK_SUPPLIER = "mock"


@dataclass(frozen=True)
class Decision:
    """How fulfilment should route this SKU.

    ``primary`` is the first thing to try; on a ``NoStockError`` from inventory,
    the fulfilment layer reads ``fallback``. ``strict`` means "do not fall back."
    """

    primary: str  # 'inventory' | 'supplier:<slug>'
    fallback: str | None  # 'supplier:<slug>' | None
    strict: bool
    rule_present: bool


async def resolve_for_sku(db: AsyncSession, sku_id: str) -> Decision:
    rule = (
        await db.execute(select(SkuSourcingRule).where(SkuSourcingRule.sku_id == sku_id))
    ).scalar_one_or_none()
    if rule is not None and rule.mode != "auto":
        return _resolve_explicit_rule(rule, sku_id=sku_id)
    return await _resolve_auto(db, sku_id=sku_id, rule_present=rule is not None)


def _resolve_explicit_rule(rule: SkuSourcingRule, *, sku_id: str) -> Decision:
    """Decision for SKUs with an admin-set ``sku_sourcing_rules`` row."""
    if rule.mode == "force_inventory":
        return Decision(primary="inventory", fallback=None, strict=True, rule_present=True)
    if rule.mode == "manual":
        # The slug is implicit (always "manual"); set_rule keeps
        # supplier_slug NULL for this mode.
        return Decision(
            primary="supplier:manual",
            fallback=None,
            strict=True,
            rule_present=True,
        )
    # force_supplier
    if not rule.supplier_slug:
        raise ValidationError(
            "sourcing rule mode is force_supplier but supplier_slug is empty",
            extra={"sku_id": sku_id},
        )
    return Decision(
        primary=f"supplier:{rule.supplier_slug}",
        fallback=None,
        strict=True,
        rule_present=True,
    )


def _pick_auto_mapping_slug(mappings: Iterable[SkuSupplierMapping]) -> str | None:
    """Which supplier the auto-routing rule treats as one SKU's route.

    The single definition of "which supplier wins": ``_resolve_auto`` (one
    query, one SKU) and the batched ``sourcing.brand_overview`` (one query
    for every SKU of a brand) both narrow a SKU's mapping rows down and
    hand them to this function instead of each re-encoding the filter and
    the tie-break. A divergence between the two would mean the brand
    overview screen reports a route an order would never actually take —
    exactly the failure mode splitting this out exists to rule out.

    Three rules here, and none of them used to exist.

    A mapping the catalogue watch has confirmed delisted is skipped
    (:data:`~yupay.modules.integrations.models.CATALOG_DELISTED`): it stays
    ``is_active`` so the watch can notice the position coming back, which is
    exactly why ``is_active`` alone cannot be the test.

    A reserve supplier is never picked automatically, whatever its mapping's
    age (`RESERVE_SUPPLIERS`, ADR-0081). Ordering alone would have made
    "reserve" an accident: it keeps the incumbent's route only while an
    incumbent exists, and a top-up SKU that never got one — or whose only
    mapping an operator deactivated mid-switch — would silently start buying
    from a supplier nobody chose. Reaching a reserve stays an explicit
    `force_supplier` decision, which is the only thing that should move
    somebody's orders.

    Among the rest, the oldest active mapping wins — the oldest is the
    incumbent, the one orders have been going to, not an accident of
    iteration order. `supplier_slug` breaks a `created_at` tie so the
    answer is total.

    `created_at` being `nullable=False` on `SkuSupplierMapping` (see
    `integrations.models`) is load-bearing for that comparison, not just a
    schema nicety: Postgres sorts `NULL` last but Python's `<` on a tuple
    containing `None` raises `TypeError` the moment two mappings are
    compared, so this function — which never touches SQL `ORDER BY` — would
    blow up on the first tie-break against a null-`created_at` row instead of
    quietly mis-ordering it. Don't drop that constraint without re-checking
    this comparison.

    Args:
        mappings: A single SKU's mapping rows, any mix of active/inactive
            and any supplier — the filtering happens in here.

    Returns:
        The winning supplier's slug, or ``None`` if no active, non-reserve
        mapping exists.
    """
    from yupay.modules.integrations.models import CATALOG_DELISTED, RESERVE_SUPPLIERS

    best: SkuSupplierMapping | None = None
    for mapping in mappings:
        if not mapping.is_active or mapping.supplier_slug in RESERVE_SUPPLIERS:
            continue
        if (mapping.extra or {}).get(CATALOG_DELISTED):
            # The supplier confirmed it no longer lists this position. The row
            # stays active as the catalogue watch's memory, so "active" alone
            # would keep routing orders to something nobody can sell us.
            continue
        # `supplier_slug` tie-break: Python codepoint order, where the old
        # SQL this replaced used the database collation. Reachable only on
        # an exact `created_at` tie; every slug in use today is
        # `[a-z0-9-]`, where codepoint order and the default (`C`-like,
        # case-sensitive) Postgres collation agree, so this has never
        # diverged — it will, the first time a slug carries non-ASCII;
        # re-check against the collation `sku_supplier_mapping.supplier_slug`
        # is actually stored under.
        if best is None or (mapping.created_at, mapping.supplier_slug) < (
            best.created_at,
            best.supplier_slug,
        ):
            best = mapping
    return best.supplier_slug if best is not None else None


def _auto_decision(*, kind: str, mapping_slug: str | None, rule_present: bool) -> Decision:
    """Kind-aware ``Decision`` given already-resolved inputs.

    The pure, return-value half of ``_resolve_auto`` — split out so
    ``sourcing.brand_overview`` can reach the identical decision from
    batch-loaded data (no query per SKU) instead of duplicating this
    branching. See ``_resolve_auto`` for how ``kind``/``mapping_slug`` are
    read on the single-SKU path.

    ``top_up`` routes to the supplier (or ``manual`` if no mapping is
    set up yet); ``voucher`` keeps the historical inventory-first
    behaviour but prefers a real configured supplier over ``mock`` for
    the fallback when one is available.
    """
    if kind == "top_up":
        if mapping_slug is None:
            # No mapping → no automated path. Route to the manual
            # admin queue so the operator either creates the mapping
            # or fulfils by hand. Don't even bother with mock — the
            # whole point is "supplier required".
            return Decision(
                primary="supplier:manual",
                fallback=None,
                strict=True,
                rule_present=rule_present,
            )
        return Decision(
            primary=f"supplier:{mapping_slug}",
            # Supplier rejection (low balance, denom gone) → admin
            # queue instead of failing the order outright.
            fallback="supplier:manual",
            strict=False,
            rule_present=rule_present,
        )

    # voucher (default for anything that isn't top_up)
    fallback_slug = mapping_slug if mapping_slug is not None else DEFAULT_FALLBACK_SUPPLIER
    return Decision(
        primary="inventory",
        fallback=f"supplier:{fallback_slug}",
        strict=False,
        rule_present=rule_present,
    )


async def _resolve_auto(db: AsyncSession, *, sku_id: str, rule_present: bool) -> Decision:
    """Kind-aware default for SKUs without an explicit rule.

    Reads the two inputs ``_auto_decision`` needs for a single SKU — the
    product kind and the winning active mapping
    (:func:`_pick_auto_mapping_slug`) — then hands them to the same pure
    decision function the batched brand-overview uses, so the two paths
    cannot disagree about which supplier wins.
    """
    # Late imports — these modules sit "above" sourcing in the
    # dependency graph (catalog is leaf, integrations imports
    # sourcing through service). Pulling them at module load creates
    # a cycle; resolving them lazily here doesn't.
    from yupay.modules.catalog.models import Product, Sku
    from yupay.modules.integrations.models import SkuSupplierMapping

    sku = (
        await db.execute(select(Sku).options(selectinload(Sku.product)).where(Sku.id == sku_id))
    ).scalar_one_or_none()
    # SKU might not exist at the call-site (e.g. test harness); fall
    # back to the pre-refactor behaviour rather than raising — the
    # downstream saga will surface the real "sku not found" error.
    product: Product | None = sku.product if sku is not None else None
    kind = product.kind if product is not None else "voucher"

    mappings = (
        (await db.execute(select(SkuSupplierMapping).where(SkuSupplierMapping.sku_id == sku_id)))
        .scalars()
        .all()
    )
    mapping_slug = _pick_auto_mapping_slug(mappings)

    return _auto_decision(kind=kind, mapping_slug=mapping_slug, rule_present=rule_present)


async def _reject_force_inventory_on_top_up_sku(db: AsyncSession, sku_id: str) -> None:
    """Refuse ``mode="force_inventory"`` for a ``top_up`` SKU.

    A top_up SKU is credited by a live supplier call, never a stocked
    code — writing this rule anyway strands every order on a guaranteed
    ``NoStockError`` with no fallback instead of the kind-aware auto route
    that at least reaches a supplier or the manual queue. Symmetric to
    ``inventory.service._reject_top_up_sku`` on the "stock a code for one"
    side of the same mistake.

    Raises:
        ValidationError: The SKU's product ``kind`` is ``top_up``.
    """
    from yupay.modules.catalog.models import Product, Sku

    kind = (
        await db.execute(
            select(Product.kind).join(Sku, Sku.product_id == Product.id).where(Sku.id == sku_id)
        )
    ).scalar_one_or_none()
    if kind == "top_up":
        raise ValidationError(
            f"SKU {sku_id} is a top_up product — the code warehouse has "
            "nothing to deliver for it; force_inventory only makes sense "
            "for a voucher SKU",
            sku_id=sku_id,
            kind=kind,
        )


async def set_rule(
    db: AsyncSession,
    *,
    sku_id: str,
    mode: Mode,
    supplier_slug: str | None,
    admin_id: str,
) -> SkuSourcingRule:
    if mode == "force_supplier" and not supplier_slug:
        raise ValidationError("supplier_slug is required for mode=force_supplier")
    if mode != "force_supplier" and supplier_slug:
        # Tolerate but ignore — keep the row clean.
        supplier_slug = None

    if mode == "force_inventory":
        await _reject_force_inventory_on_top_up_sku(db, sku_id)

    # Lazy for the reason ``resolve_for_sku`` gives: a top-level import of
    # ``integrations``/``fulfillment`` from here closes a cycle.
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.integrations.models import MAPPING_REQUIRED_SUPPLIERS, SkuSupplierMapping

    if mode == "force_supplier" and supplier_slug not in REGISTRY:
        # set_rule is the only place a supplier_slug is ever written, so this
        # is the one gate against a typo ("waxpeeer") being accepted as a
        # successful rule change — every order routed through it would
        # otherwise fail one at a time with get_fulfiller's 404, discovered
        # only after the operator believes the switch worked. Flat kwarg, not
        # extra={...} — see bulk_rules.bulk_set_rules for the same fix.
        raise ValidationError(
            f"unknown fulfilment supplier: {supplier_slug!r} — not registered in "
            "fulfillment.suppliers.REGISTRY",
            supplier_slug=supplier_slug,
        )

    if mode == "force_supplier" and supplier_slug in MAPPING_REQUIRED_SUPPLIERS:
        # Forcing a SKU onto G2B or G-Engine with no mapping row does not
        # route it there — it fails every order with "no active mapping".
        mapped = (
            await db.execute(
                select(SkuSupplierMapping.supplier_slug).where(
                    SkuSupplierMapping.sku_id == sku_id,
                    SkuSupplierMapping.supplier_slug == supplier_slug,
                    SkuSupplierMapping.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if mapped is None:
            raise ValidationError(
                f"no active {supplier_slug} mapping for this SKU — create it under "
                "Integrations → Mappings before routing orders there"
            )

    existing = (
        await db.execute(select(SkuSourcingRule).where(SkuSourcingRule.sku_id == sku_id))
    ).scalar_one_or_none()
    if existing is None:
        existing = SkuSourcingRule(
            sku_id=sku_id,
            mode=mode,
            supplier_slug=supplier_slug,
            updated_by=admin_id,
        )
        db.add(existing)
    else:
        existing.mode = mode
        existing.supplier_slug = supplier_slug
        existing.updated_by = admin_id
        existing.updated_at = now()
    await db.flush()
    return existing


async def get_rule(db: AsyncSession, sku_id: str) -> SkuSourcingRule | None:
    return (
        await db.execute(select(SkuSourcingRule).where(SkuSourcingRule.sku_id == sku_id))
    ).scalar_one_or_none()


async def list_rules(db: AsyncSession, limit: int = 200) -> list[SkuSourcingRule]:
    return list(
        (
            await db.execute(
                select(SkuSourcingRule)
                .order_by(SkuSourcingRule.updated_at.desc())
                .limit(min(limit, 500))
            )
        )
        .scalars()
        .all()
    )


async def delete_rule(db: AsyncSession, sku_id: str) -> None:
    rule = await get_rule(db, sku_id)
    if rule is None:
        raise NotFoundError("sourcing rule not found")
    await db.delete(rule)
    await db.flush()


async def sku_codes_for(db: AsyncSession, sku_ids: Iterable[str]) -> dict[str, str]:
    """Batch-resolve ``sku_id -> sku_code`` for the given ids — one query, no N+1.

    ``SkuSourcingRule`` carries only ``sku_id`` (no ORM relationship to
    ``Sku``); admin list views need the human-readable code instead of a raw
    UUID, so routes call this once after fetching rule rows.
    """
    from yupay.modules.catalog.models import Sku

    ids = list(dict.fromkeys(sku_ids))
    if not ids:
        return {}
    rows = (await db.execute(select(Sku.id, Sku.sku_code).where(Sku.id.in_(ids)))).all()
    return {row.id: row.sku_code for row in rows}


__all__ = [
    "DEFAULT_FALLBACK_SUPPLIER",
    "Decision",
    "Mode",
    "delete_rule",
    "get_rule",
    "list_rules",
    "resolve_for_sku",
    "set_rule",
    "sku_codes_for",
]
