"""Amount and provider rules for customer wallet top-up (ADR-0058).

Currency is derived from the acquirer, never from the client. Paying from
the in-house wallet is not a top-up.
"""

from __future__ import annotations

from decimal import Decimal

from yupay.core.errors import ValidationError

#: Acquirer slug → ledger / charge currency. Missing slug is a 422, not a guess.
PROVIDER_CURRENCY: dict[str, str] = {
    "click": "UZS",
    "click_miniapp": "UZS",
    "payme": "UZS",
    "uzum": "UZS",
    "octo": "UZS",
    "crypto": "USDT",
    "mock": "UZS",
}

BLOCKED_PROVIDERS: frozenset[str] = frozenset({"wallet"})

# min, max, quantum (inclusive bounds).
_LIMITS: dict[str, tuple[Decimal, Decimal, Decimal]] = {
    "UZS": (Decimal("10000"), Decimal("5000000"), Decimal("1")),
    "USDT": (Decimal("5"), Decimal("500"), Decimal("0.01")),
}

PURPOSE_WALLET_TOPUP = "wallet_topup"
PURPOSE_CATALOG = "catalog"


def currency_for_provider(provider: str) -> str:
    """Return the charge currency, or raise if the slug cannot fund a wallet."""
    if provider in BLOCKED_PROVIDERS:
        raise ValidationError(
            "cannot top up the wallet by paying from the wallet",
            extra={"provider": provider},
        )
    currency = PROVIDER_CURRENCY.get(provider)
    if currency is None:
        raise ValidationError(
            "provider cannot fund the wallet",
            extra={"provider": provider},
        )
    return currency


def quantize_topup_amount(amount: Decimal, currency: str) -> Decimal:
    """Clamp to the currency quantum. Raises if the amount is out of bounds
    or not aligned to the quantum (we do not silently round a customer's
    figure — 10 000.5 UZS is a 422, not 10 000).
    """
    limits = _LIMITS.get(currency)
    if limits is None:
        raise ValidationError(
            "currency cannot fund the wallet",
            extra={"currency": currency},
        )
    minimum, maximum, quantum = limits
    if amount <= 0:
        raise ValidationError("amount must be positive")
    quantized = amount.quantize(quantum)
    if quantized != amount:
        raise ValidationError(
            "amount is not aligned to the currency quantum",
            extra={"amount": str(amount), "quantum": str(quantum), "currency": currency},
        )
    if quantized < minimum:
        raise ValidationError(
            "amount is below the minimum",
            extra={"amount": str(quantized), "min": str(minimum), "currency": currency},
        )
    if quantized > maximum:
        raise ValidationError(
            "amount is above the maximum",
            extra={"amount": str(quantized), "max": str(maximum), "currency": currency},
        )
    return quantized
