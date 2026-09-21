"""The per-merchant price adjustment, and the one check that makes it safe.

``merchants.markup_adjustment_pp`` has been on the row since M1 and has been
dormant since: the column existed, ``pricing.merchant_markup_pct`` already
added it to every SKU's own markup, and nothing could set it. This module is
the setter.

## Why a write-time check, and what it is not

The adjustment is in percentage points and applies to the **whole** catalogue
at once, so one number decides whether that merchant can buy anything. With
the catalogue at ``b2b_markup_pct = 7`` and ``merchant_margin_floor_pct = 2``,
an adjustment of ``-5`` is the edge and ``-6`` makes every order that merchant
places fail with ``margin_floor`` — at order time, one order at a time, with
nothing on the merchant page hinting why.

So the same arithmetic runs here, against the cheapest markup the merchant can
actually see, and refuses. That moves a failure from "every order, later" to
"this save, now", which is the same trade the deposit debit's overdraw guard
makes.

**It is a guard, not a guarantee.** The set of SKUs a merchant sees changes:
a SKU imported tomorrow at a thinner markup can put a previously-fine
adjustment under the floor. ``quote.py``'s order-time check is still the
authority and stays exactly where it is. What this prevents is the mistake
that is knowable at the moment it is made.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from yupay.core.config import get_settings
from yupay.core.errors import ValidationError
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.merchants.models import Merchant
from yupay.modules.merchants.service import get_merchant

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

#: RFC 7807 ``code`` for an adjustment that would put the merchant's cheapest
#: SKU under the margin floor. Its own code because the fix is a number, and
#: an operator needs to know which number.
CODE_BELOW_FLOOR = "markup_below_floor"

log = get_logger("yupay.merchants.markup")


async def _thinnest_visible_markup(db: AsyncSession) -> Decimal | None:
    """The smallest ``b2b_markup_pct`` anybody can buy at.

    Scoped the way ``price_list.build`` scopes what a merchant sees —
    ``brand.visible_b2b AND sku.visible_b2b``, both active — because a markup
    on a SKU they cannot order is not a constraint on their price.

    No ``merchant_id``: B2B visibility is uniform across merchants by design
    (spec §8.3), and the adjustment is the only per-merchant term in the
    price. The day visibility stops being uniform, this is the function that
    grows the argument.

    Returns:
        The minimum, or ``None`` when nothing is on sale to resellers at all
        — in which case no adjustment can break an order nobody can place.
    """
    stmt = (
        select(func.min(Sku.b2b_markup_pct))
        .select_from(Sku)
        .join(Product, Product.id == Sku.product_id)
        .join(Brand, Brand.id == Product.brand_id)
        .where(
            Sku.active.is_(True),
            Sku.visible_b2b.is_(True),
            Brand.active.is_(True),
            Brand.visible_b2b.is_(True),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def set_markup_adjustment(
    db: AsyncSession, *, merchant_id: str, adjustment: Decimal | None
) -> Merchant:
    """Set (or clear) a merchant's catalogue-wide price adjustment.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose price to adjust. Must exist.
        adjustment: Percentage points added to every SKU's own markup.
            Negative for a negotiated discount. ``None`` restores the
            catalogue price.

    Returns:
        The updated merchant row.

    Raises:
        NotFoundError: If no merchant with that id exists.
        ValidationError: ``markup_below_floor`` — the adjustment would put
            the merchant's cheapest visible SKU under
            ``settings.merchant_margin_floor_pct``, so every order they place
            would be refused.
    """
    merchant = await get_merchant(db, merchant_id)
    if adjustment is not None and adjustment < 0:
        thinnest = await _thinnest_visible_markup(db)
        floor = get_settings().merchant_margin_floor_pct
        if thinnest is not None and thinnest + adjustment < floor:
            raise ValidationError(
                "this adjustment would put the cheapest SKU under the margin floor, "
                "so every order this merchant places would be refused",
                code=CODE_BELOW_FLOOR,
                # Kwargs, not `extra={...}`: `AppError.__init__` collects
                # `**extra` and the handler flattens it into the problem+json
                # body, so a dict here would publish one nested `extra` key
                # instead of three readable ones.
                thinnest_markup_pct=str(thinnest),
                floor_pct=str(floor),
                # The number that WOULD work, so the fix is a value and not
                # an experiment.
                lowest_allowed_pp=str(floor - thinnest),
            )
    merchant.markup_adjustment_pp = adjustment
    await db.flush()
    # A price decision, and the only record of who made it beyond the row
    # itself. The value is a number, not PII, and it is the thing a later
    # "why is this reseller cheaper" needs.
    log.info(
        "merchant.markup_adjusted",
        merchant_id=merchant_id,
        adjustment_pp=str(adjustment),
    )
    return merchant


__all__ = ["CODE_BELOW_FLOOR", "set_markup_adjustment"]
