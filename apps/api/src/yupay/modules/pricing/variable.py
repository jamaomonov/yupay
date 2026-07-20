"""Pricing for SKUs whose amount the customer chooses.

Two conversions live here and nowhere else:

* **amount → supplier units.** Waxpeer counts in thousandths of a dollar, and
  any fee it charges must be grossed up so the customer still receives what
  they asked for. Rounding is always up: the most we lose is a cent, and the
  customer is never short-changed.
* **amount → price.** The customer-facing rate is the market rate times the
  SKU's multiplier, which is where our margin lives — there is no separate
  percentage shown anywhere.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from yupay.core.errors import ValidationError

UNITS_PER_USD = 1000
_CENT = Decimal("0.01")


def to_units(amount_usd: Decimal, *, fee_rate: Decimal) -> int:
    """Supplier units to send so the wallet receives ``amount_usd``.

    Raises:
        ValidationError: If ``amount_usd`` is not positive, or if ``fee_rate``
            is outside [0, 1).
    """
    if amount_usd <= 0:
        raise ValidationError("amount must be positive", extra={"amount_usd": str(amount_usd)})
    if fee_rate < 0 or fee_rate >= 1:
        raise ValidationError("fee rate must be in [0, 1)", extra={"fee_rate": str(fee_rate)})
    gross = amount_usd / (Decimal("1") - fee_rate)
    return int((gross * UNITS_PER_USD).to_integral_value(rounding=ROUND_CEILING))


def display_rate(market_rate: Decimal, multiplier: Decimal) -> Decimal:
    """Rate shown to the customer — margin included."""
    return market_rate * multiplier


def price_in_quote(amount_usd: Decimal, *, rate: Decimal) -> Decimal:
    """What the customer pays, in the quote currency's own units.

    ``rate`` is the customer-facing rate from :func:`display_rate`, not the raw
    market rate — the parameter is deliberately not called ``display_rate`` so
    it cannot shadow that function at call sites.

    Six decimals are used for intermediate precision here; rounding to the
    currency's actual minor units (UZS/RUB both have 2 decimals) happens when
    the full order total is assembled at checkout.
    """
    return (amount_usd * rate).quantize(Decimal("1.000000"), rounding=ROUND_HALF_UP)


def validate_amount(amount_usd: Decimal, *, minimum: Decimal, maximum: Decimal) -> None:
    """Reject anything the supplier or the SKU will not accept.

    Raises:
        ValidationError: If ``amount_usd`` has more than two decimals, or if it
            is outside the closed interval [minimum, maximum].
    """
    if amount_usd.quantize(_CENT) != amount_usd:
        raise ValidationError(
            "amount supports at most two decimals", extra={"amount": str(amount_usd)}
        )
    if amount_usd < minimum or amount_usd > maximum:
        raise ValidationError(
            "amount is outside the allowed range",
            extra={"amount": str(amount_usd), "min": str(minimum), "max": str(maximum)},
        )
