"""Price a CS2 skin order line from the live listing the customer picked.

Same contract as ``gifts.checkout.price_gift_line`` (ADR-0066): the client's amount is a
courtesy check within ±2 %, the server's number is what gets billed, and the line is
snapshotted with everything fulfilment needs (``expected_units`` — the most we will pay
Waxpeer for it — the market name, the phase, the canonical trade link).

Rules specific to skins (plan 3a, owner 2026-09-28):

* a signed-in customer only — a failed purchase refunds to their YuPay balance;
* one listing per line (``qty`` 1);
* the trade link must belong to the customer's linked Steam account when they have one;
* a listing that is gone answers with the next offer, so the page can offer it.

``live_listings`` reads through ``skins.listings.listings_for``: Redis-cached (90 s),
budgeted, degradable — the same read the item page already made a moment ago, so a
checkout normally costs no upstream call.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.config import get_settings
from yupay.core.errors import UnauthorizedError, ValidationError
from yupay.core.redis import get_redis
from yupay.modules.fulfillment.suppliers.waxpeer_client import WaxpeerClient
from yupay.modules.skins.listings import Listing, listings_for
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.pricing import quote
from yupay.modules.skins.settings import enabled_categories, load_rules
from yupay.modules.skins.tradelink import parse_tradelink, save_trade_link
from yupay.modules.users.models import SteamLink

CS2_SKIN_SKU_CODE = "cs2-skin"
_PRICE_TOLERANCE = Decimal("0.02")


def is_skin_sku(sku: object) -> bool:
    """True for the single CS2 skin SKU (duck-typed, like ``is_gift_sku``)."""
    return getattr(sku, "sku_code", None) == CS2_SKIN_SKU_CODE


async def live_listings(item: SkinItem) -> list[Listing]:
    """The item's current auto listings (cached, budgeted, degradable)."""
    settings = get_settings()
    client = WaxpeerClient(
        api_key=settings.waxpeer_api_key,
        base_url=settings.waxpeer_base_url,
        timeout_seconds=settings.cs2_skins_listings_timeout_seconds,
    )
    rows, _degraded = await listings_for(
        item,
        client=client,
        redis=get_redis(),
        budget_per_minute=settings.cs2_skins_listings_bucket_per_minute
        if settings.waxpeer_api_key
        else 0,
    )
    return rows


def _listing_id(data: dict[str, Any]) -> int:
    try:
        return int(data.get("listing_id"))  # type: ignore[arg-type] # validated below
    except (TypeError, ValueError) as exc:
        raise ValidationError("listing_id must be a number") from exc


async def _item(db: AsyncSession, slug: str) -> SkinItem:
    item = (
        await db.execute(
            select(SkinItem).where(
                SkinItem.slug == slug,
                SkinItem.active.is_(True),
                SkinItem.category.in_(enabled_categories(get_settings())),
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise ValidationError("this skin is not on sale", extra={"reason": "listing_gone"})
    return item


async def _check_owner(db: AsyncSession, *, user_id: str, steam_id: int) -> None:
    linked = (
        await db.execute(select(SteamLink.steam_id).where(SteamLink.user_id == user_id))
    ).scalar_one_or_none()
    if linked is not None and int(linked) != steam_id:
        raise ValidationError(
            "this trade link belongs to another Steam account",
            extra={"reason": "tradelink_other_account"},
        )


async def price_skin_line(
    db: AsyncSession,
    *,
    user_id: str | None,
    qty: int,
    line_amount_usd: Decimal | None,
    data: dict[str, Any],
) -> tuple[Decimal, dict[str, Any]]:
    """Re-price one skin line; returns ``(unit_price_usd, enriched fulfillment_data)``.

    Raises:
        UnauthorizedError: a guest (or a merchant) — skins need a YuPay balance.
        ValidationError: bad link, someone else's account, gone listing (with
            ``next_offer``), or a price that moved beyond ±2 % (with
            ``expected_amount_usd``).
    """
    if user_id is None:
        raise UnauthorizedError("sign in to buy a skin")
    if qty != 1:
        raise ValidationError("a skin line is one item")
    link = parse_tradelink(str(data.get("tradelink") or ""))
    await _check_owner(db, user_id=user_id, steam_id=link.steam_id)

    item = await _item(db, str(data.get("slug") or ""))
    listing_id = _listing_id(data)
    rules = await load_rules(db)

    def price_of(units: int) -> Decimal:
        return quote(
            units,
            rules=rules,
            category=item.category,
            weapon=item.weapon,
            count_auto=item.count_auto,
            item_pp=item.margin_override_pp,
            fixed_price_usd=item.fixed_price_usd,
            steam_price_units=item.steam_price_units,
        ).price_usd

    live = await live_listings(item)
    chosen = next((row for row in live if row.listing_id == listing_id), None)
    if chosen is None:
        cheapest = min(live, key=lambda row: row.price_units, default=None)
        extra: dict[str, Any] = {"reason": "listing_gone"}
        if cheapest is not None:
            extra["next_offer"] = {
                "listing_id": cheapest.listing_id,
                "price_usd": str(price_of(cheapest.price_units)),
            }
        raise ValidationError("this offer has just been sold", extra=extra)

    expected = price_of(chosen.price_units)
    if line_amount_usd is None:
        raise ValidationError("amount is required for this product")
    if abs(line_amount_usd - expected) > expected * _PRICE_TOLERANCE:
        raise ValidationError(
            "the price of this skin has changed — refresh and try again",
            extra={"expected_amount_usd": str(expected)},
        )

    data.update(
        {
            "slug": item.slug,
            "listing_id": chosen.listing_id,
            "tradelink": link.url,
            "market_hash_name": item.market_hash_name,
            "phase": item.phase,
            "name": f"{item.market_hash_name} {item.phase}".strip(),
            "expected_units": chosen.price_units,
            "float_value": chosen.float_value,
        }
    )
    await save_trade_link(db, user_id=user_id, url=link.url, steam_id=link.steam_id)
    return expected, data


def skin_label(data: dict[str, Any]) -> str | None:
    """The line's display name, snapshotted at checkout."""
    name = data.get("name")
    return str(name) if name else None


__all__ = ["CS2_SKIN_SKU_CODE", "is_skin_sku", "live_listings", "price_skin_line", "skin_label"]
