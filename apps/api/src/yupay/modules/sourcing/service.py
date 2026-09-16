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
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.sourcing.models import SkuSourcingRule

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
        # Manual fulfilment — the order ends up in the admin queue. The slug
        # is implicit (always ``"manual"``); ``set_rule`` keeps the
        # ``supplier_slug`` column NULL for this mode.
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


async def _resolve_auto(db: AsyncSession, *, sku_id: str, rule_present: bool) -> Decision:
    """Kind-aware default for SKUs without an explicit rule.

    ``top_up`` routes to the supplier (or ``manual`` if no mapping is
    set up yet); ``voucher`` keeps the historical inventory-first
    behaviour but prefers a real configured supplier over ``mock`` for
    the fallback when one is available.
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

    # Active mappings — order doesn't matter; we only need to know if
    # there's at least one usable supplier slug. For voucher this picks
    # the fallback supplier; for top_up it picks the primary.
    mapping_slug: str | None = (
        await db.execute(
            select(SkuSupplierMapping.supplier_slug)
            .where(
                SkuSupplierMapping.sku_id == sku_id,
                SkuSupplierMapping.is_active.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()

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
    # Lazy for the reason ``resolve_for_sku`` gives: a top-level import of
    # ``integrations`` from here closes a cycle.
    from yupay.modules.integrations.models import MAPPING_REQUIRED_SUPPLIERS, SkuSupplierMapping

    if mode == "force_supplier" and supplier_slug in MAPPING_REQUIRED_SUPPLIERS:
        # Forcing a SKU onto G2B or G-Engine with no mapping row does not
        # route it there — it fails every order that arrives, one at a time,
        # with "no active mapping" in the inbox. The operator's intent was
        # "use this supplier", and the honest answer is that it cannot be used
        # yet, at the moment they say so rather than at the first sale.
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
