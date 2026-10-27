"""A hand-filled SKU's cost, kept in the currency the operator pays in.

Some goods have no supplier API: the order lands in the manual queue and an
operator buys the goods by hand — Standoff 2 Gold from the official store,
priced in roubles (2026-10-27). ``Sku.cost_usdt`` is still our cost basis
(retail price, the order line's frozen cost and the margin report all read it),
so a rouble price has to become dollars — and keep becoming dollars as the
rate moves, or the margin quietly erodes.

The price lives on the SKU's ``manual`` mapping:
``extra = {"cost": "119", "cost_currency": "RUB"}``. The hourly price refresh
treats ``manual`` like any supplier whose price it collects: this module turns
that amount into USD at the rate the system uses (``FxService.get_rate``, so an
admin-pinned rate wins), and ``cost_refresh`` writes it. The usual rules hold:
the automatic pass never lowers a shelf price, it only widens the margin.

A ``manual`` mapping only routes to the manual queue — the mapping is where the
price lives, not a supplier — so ``sourcing`` sends the order exactly where it
went without one.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING, Final

from yupay.modules.integrations.cost_lookup import _RawPrice

if TYPE_CHECKING:
    from yupay.modules.integrations.models import SkuSupplierMapping

#: ``mapping.extra`` keys for the operator's purchase price.
COST_KEY: Final = "cost"
CURRENCY_KEY: Final = "cost_currency"

_SIX_PLACES = Decimal("0.000001")
_NO_PRICE: Final = _RawPrice(
    amount=None, source="", reason="у ручного маппинга не указана цена закупки"
)


async def manual_raw_price(mapping: SkuSupplierMapping) -> _RawPrice:
    """The mapping's purchase price in USD at today's rate.

    Returns:
        The USD amount with ``source="manual:<CUR>@<rate>"``, or a reason when
        the mapping carries no usable price or no rate is available.
    """
    from yupay.modules.fx.factory import build_default_service
    from yupay.modules.fx.service import FxUnavailableError

    extra = mapping.extra or {}
    currency = str(extra.get(CURRENCY_KEY) or "USD").strip().upper()
    try:
        amount = Decimal(str(extra.get(COST_KEY)))
    except (InvalidOperation, ValueError):
        return _NO_PRICE
    if not amount.is_finite() or amount <= 0:
        return _NO_PRICE
    if currency == "USD":
        return _RawPrice(amount=amount, source="manual:USD")
    try:
        quote = await build_default_service().get_rate("USD", currency)
    except FxUnavailableError:
        return _RawPrice(amount=None, source="", reason=f"нет курса USD→{currency}")
    if quote.rate <= 0:
        return _RawPrice(amount=None, source="", reason=f"курс USD→{currency} ≤ 0")
    usd = (amount / quote.rate).quantize(_SIX_PLACES, rounding=ROUND_HALF_UP)
    return _RawPrice(amount=usd, source=f"manual:{currency}@{quote.rate.normalize():f}")


__all__ = ["COST_KEY", "CURRENCY_KEY", "manual_raw_price"]
