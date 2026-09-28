"""Write each row's sell price and discount from the pricing rules.

Runs after every price tick (inside ``sync_prices``' transaction) and after
every rules write or per-item override (inside the admin transaction), so
the stored numbers never disagree with what ``quote()`` would say.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.pricing import PricingRules, quote

_BATCH = 1000


def discount_of(price: Decimal, steam_price_units: int | None) -> int | None:
    """Whole percent below Steam, truncated toward zero (negative when dearer)."""
    if not steam_price_units:
        return None
    steam = Decimal(steam_price_units) / Decimal(1000)
    return int((steam - price) / steam * 100)


async def reprice_rows(
    db: AsyncSession, rules: PricingRules, *, ids: Sequence[str] | None = None
) -> int:
    """Recompute ``sell_price_usd``/``discount_percent``; returns rows written."""
    stmt = select(SkinItem)
    if ids is not None:
        stmt = stmt.where(SkinItem.id.in_(ids))
    rows = (await db.execute(stmt)).scalars().all()
    updates: list[dict[str, object]] = []
    for row in rows:
        if not row.active or row.min_auto_units is None:
            price, discount = None, None
        else:
            price = quote(
                row.min_auto_units,
                rules=rules,
                category=row.category,
                weapon=row.weapon,
                count_auto=row.count_auto,
                item_pp=row.margin_override_pp,
                fixed_price_usd=row.fixed_price_usd,
                steam_price_units=row.steam_price_units,
            ).price_usd
            discount = discount_of(price, row.steam_price_units)
        if (price, discount) != (row.sell_price_usd, row.discount_percent):
            updates.append({"id": row.id, "sell_price_usd": price, "discount_percent": discount})
    for start in range(0, len(updates), _BATCH):
        await db.execute(update(SkinItem), updates[start : start + _BATCH])
    return len(updates)


__all__ = ["discount_of", "reprice_rows"]
