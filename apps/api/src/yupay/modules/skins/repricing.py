"""Write each row's sell price and discount from the pricing rules.

Runs after every price tick (inside ``sync_prices``' transaction) and after
every rules write or per-item override (inside the admin transaction), so
the stored numbers never disagree with what ``quote()`` would say.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.pricing import PricingRules, quote

_BATCH = 1000
#: ``pg_advisory_xact_lock`` key serialising every whole-catalogue reprice
#: ("skin" in ASCII). Held to the end of the caller's transaction.
PRICING_LOCK_KEY = 0x736B696E


async def lock_pricing(db: AsyncSession) -> None:
    """Serialise repricing writers: the price tick and the admin rule/item writes.

    Take it first in the transaction, before reading the rules, so a tick can
    never price from rules an admin is replacing at that moment.
    """
    await db.execute(select(func.pg_advisory_xact_lock(PRICING_LOCK_KEY)))


def discount_of(price: Decimal, steam_price_units: int | None) -> int | None:
    """Whole percent below Steam, truncated toward zero (negative when dearer)."""
    if not steam_price_units:
        return None
    steam = Decimal(steam_price_units) / Decimal(1000)
    return int((steam - price) / steam * 100)


async def reprice_rows(
    db: AsyncSession, rules: PricingRules, *, ids: Sequence[str] | None = None
) -> int:
    """Recompute ``sell_price_usd``/``discount_percent``; returns rows written.

    Reads only the columns ``quote()`` needs, and only active rows: an inactive
    row's price is cleared by one ``UPDATE`` rather than loaded to learn it.
    """
    cleared = update(SkinItem).where(
        SkinItem.active.is_(False),
        (SkinItem.sell_price_usd.is_not(None)) | (SkinItem.discount_percent.is_not(None)),
    )
    stmt = select(
        SkinItem.id,
        SkinItem.min_auto_units,
        SkinItem.category,
        SkinItem.weapon,
        SkinItem.count_auto,
        SkinItem.margin_override_pp,
        SkinItem.fixed_price_usd,
        SkinItem.steam_price_units,
        SkinItem.sell_price_usd,
        SkinItem.discount_percent,
    ).where(SkinItem.active.is_(True))
    if ids is not None:
        cleared = cleared.where(SkinItem.id.in_(ids))
        stmt = stmt.where(SkinItem.id.in_(ids))
    result = await db.execute(cleared.values(sell_price_usd=None, discount_percent=None))
    written = int(getattr(result, "rowcount", 0) or 0)  # CursorResult; typed as Result
    updates: list[dict[str, object]] = []
    for row in (await db.execute(stmt)).all():
        if row.min_auto_units is None:
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
    return written + len(updates)


__all__ = ["PRICING_LOCK_KEY", "discount_of", "lock_pricing", "reprice_rows"]
