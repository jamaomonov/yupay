"""Sourcing service: per-SKU decision rules.

Default behaviour (no row in ``sku_sourcing_rules``) is **inventory-first with
fallback to the mock supplier**. The default fallback supplier slug is hard-coded
to ``mock`` here while real adapters land; later it'll move to a config setting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.sourcing.models import SkuSourcingRule

Mode = Literal["auto", "force_inventory", "force_supplier"]
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
        await db.execute(
            select(SkuSourcingRule).where(SkuSourcingRule.sku_id == sku_id)
        )
    ).scalar_one_or_none()
    if rule is None or rule.mode == "auto":
        return Decision(
            primary="inventory",
            fallback=f"supplier:{DEFAULT_FALLBACK_SUPPLIER}",
            strict=False,
            rule_present=rule is not None,
        )
    if rule.mode == "force_inventory":
        return Decision(
            primary="inventory", fallback=None, strict=True, rule_present=True
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

    existing = (
        await db.execute(
            select(SkuSourcingRule).where(SkuSourcingRule.sku_id == sku_id)
        )
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
        await db.execute(
            select(SkuSourcingRule).where(SkuSourcingRule.sku_id == sku_id)
        )
    ).scalar_one_or_none()


async def list_rules(db: AsyncSession, limit: int = 200) -> list[SkuSourcingRule]:
    return list(
        (
            await db.execute(
                select(SkuSourcingRule)
                .order_by(SkuSourcingRule.updated_at.desc())
                .limit(min(limit, 500))
            )
        ).scalars().all()
    )


async def delete_rule(db: AsyncSession, sku_id: str) -> None:
    rule = await get_rule(db, sku_id)
    if rule is None:
        raise NotFoundError("sourcing rule not found")
    await db.delete(rule)
    await db.flush()


__all__ = [
    "DEFAULT_FALLBACK_SUPPLIER",
    "Decision",
    "Mode",
    "delete_rule",
    "get_rule",
    "list_rules",
    "resolve_for_sku",
    "set_rule",
]
