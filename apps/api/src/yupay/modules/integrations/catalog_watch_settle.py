"""What a confirmed delisting does to the SKU — the deciding half of the
catalogue watch.

:mod:`catalog_watch` notices that one supplier stopped listing a position and
confirms it on a second tick. Until 2026-09-25 the confirmation switched the
SKU off, full stop. That is only right when the SKU has nothing else to be
bought from. That day G-Engine dropped six Blood Strike packs: five of those
SKUs were routed to FazerCards, all six were still carried by G2B, FazerCards
and NOVA, and every one of them came off the shelf anyway.

So a confirmed delisting now asks where the SKU is actually bought:

1. **Somewhere else** — the supplier that dropped it is not the route. The
   shelf is untouched; the mapping is marked so routing never picks it.
2. **Here, and another non-reserve mapping is live** — the SKU moves to it.
   A ``force_supplier`` rule naming the delisted supplier is dropped so auto
   routing can take over, and the SKU is re-priced on the new supplier at
   once (``allow_price_drop=False``, as for an operator's switch — ADR-0091),
   because the alternative is selling at the old supplier's price until the
   next hourly tick.
3. **Here, and nothing else can take it** — the SKU goes off, as before. A
   reserve (FazerCards, NOVA) is never reached automatically (ADR-0081), so
   when only reserves remain the alert names them and leaves the switch to a
   person.

Every outcome sends one alert; the mark on the mapping is what stops the next
tick from sending it again.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Sku
from yupay.modules.integrations.models import (
    CATALOG_DELISTED,
    RESERVE_SUPPLIERS,
    SkuSupplierMapping,
)

log = get_logger("yupay.integrations.catalog_watch")

SendAlert = Callable[..., Awaitable[bool]]

#: Routes that are not a supplier we buy from, so they can never be "the
#: supplier that delisted it".
_NOT_A_SUPPLIER = frozenset({"manual", "mock"})

_KEPT_NOTE = "Маппинг сохранён — если позиция вернётся, придёт отдельное уведомление."


async def route_slug(db: AsyncSession, sku_id: str) -> str | None:
    """The supplier this SKU's orders go to, or ``None`` for none.

    A voucher routes to the warehouse first and a supplier second; the
    supplier is the one a delisting can take away, so that is what counts.
    """
    from yupay.modules.sourcing.service import resolve_for_sku

    decision = await resolve_for_sku(db, sku_id)
    target = decision.primary if decision.primary.startswith("supplier:") else decision.fallback
    if not target or not target.startswith("supplier:"):
        return None
    slug = target.split(":", 1)[1]
    return None if slug in _NOT_A_SUPPLIER else slug


async def _reprice(db: AsyncSession, sku_id: str) -> str | None:
    """Put the SKU's cost and price on its new route. ``None`` on success,
    else the reason, for the alert — the route change stands either way."""
    from yupay.modules.integrations.cost_refresh import refresh_routed_cost

    try:
        outcome = await refresh_routed_cost(db, sku_id=sku_id, allow_price_drop=False)
    except Exception as exc:  # noqa: BLE001 -- the switch must stand; say what failed
        log.warning(
            "integrations.catalog_watch.reprice_failed", sku_id=sku_id, error=str(exc)[:200]
        )
        return f"себестоимость не обновлена: {exc}"[:200]
    return None if outcome.wrote_cost or outcome.updated else outcome.reason


async def _mappings(db: AsyncSession, sku_id: str) -> list[SkuSupplierMapping]:
    rows = await db.execute(select(SkuSupplierMapping).where(SkuSupplierMapping.sku_id == sku_id))
    return list(rows.scalars().all())


def _live(mapping: SkuSupplierMapping) -> bool:
    return mapping.is_active and not (mapping.extra or {}).get(CATALOG_DELISTED)


async def _drop_rule_naming(db: AsyncSession, sku_id: str, supplier: str) -> bool:
    """Remove a ``force_supplier`` rule pointing at ``supplier``. True if one went."""
    from yupay.modules.sourcing.models import SkuSourcingRule

    result = await db.execute(
        delete(SkuSourcingRule)
        .where(
            SkuSourcingRule.sku_id == sku_id,
            SkuSourcingRule.mode == "force_supplier",
            SkuSourcingRule.supplier_slug == supplier,
        )
        .returning(SkuSourcingRule.sku_id)
    )
    return result.first() is not None


async def settle_delisting(
    db: AsyncSession,
    mapping: SkuSupplierMapping,
    sku: Sku,
    *,
    position: str,
    send_alert: SendAlert,
) -> bool:
    """Act on one confirmed delisting. Returns True only if the SKU went off."""
    from yupay.modules.sourcing.service import _pick_auto_mapping_slug

    supplier = mapping.supplier_slug
    head = f"🗑 Поставщик {supplier} убрал из каталога «{position}»."
    before = await route_slug(db, sku.id)
    mapping.extra = {**mapping.extra, CATALOG_DELISTED: True}
    await db.flush()

    if before != supplier:
        where = before or "склад или ручную выдачу"
        log.info(
            "integrations.catalog_watch.delisted_off_route",
            supplier=supplier,
            sku_code=sku.sku_code,
            route=before,
        )
        await send_alert(
            f"{head}\nSKU {sku.sku_code} покупается через {where} — на витрине ничего "
            f"не меняется, {supplier} для него больше не выбирается.\n{_KEPT_NOTE}",
            kind="catalog_watch",
        )
        return False

    mappings = await _mappings(db, sku.id)
    if _pick_auto_mapping_slug(mappings) is not None:
        handed_over = await _drop_rule_naming(db, sku.id, supplier)
        after = await route_slug(db, sku.id)
        if after is not None and after != supplier:
            problem = await _reprice(db, sku.id)
            log.warning(
                "integrations.catalog_watch.route_moved",
                supplier=supplier,
                sku_code=sku.sku_code,
                route=after,
                rule_dropped=handed_over,
            )
            rule_note = f" Правило «только {supplier}» снято." if handed_over else ""
            price_note = (
                f"Цена не пересчитана: {problem}"
                if problem
                else "Цена пересчитана по новому поставщику."
            )
            await send_alert(
                f"{head}\nSKU {sku.sku_code} переключён на {after} и остаётся на витрине."
                f"{rule_note}\n{price_note}\n{_KEPT_NOTE}",
                kind="catalog_watch",
            )
            return False

    sku.active = False
    reserves = sorted(
        m.supplier_slug for m in mappings if m.supplier_slug in RESERVE_SUPPLIERS and _live(m)
    )
    log.warning(
        "integrations.catalog_watch.sku_deactivated",
        supplier=supplier,
        sku_code=sku.sku_code,
        reserves=reserves,
    )
    reserve_note = (
        f"\nПозиция есть у резервных поставщиков: {', '.join(reserves)} — можно включить SKU "
        "и направить туда правилом «только поставщик»."
        if reserves
        else ""
    )
    await send_alert(
        f"{head}\nSKU {sku.sku_code} деактивирован и снят с витрины.{reserve_note}\n{_KEPT_NOTE}",
        kind="catalog_watch",
    )
    return True


__all__ = ["route_slug", "settle_delisting"]
