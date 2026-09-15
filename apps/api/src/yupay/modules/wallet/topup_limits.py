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
    "paynet": "UZS",
    "crypto": "USDT",
    "mock": "UZS",
}

BLOCKED_PROVIDERS: frozenset[str] = frozenset({"wallet"})

#: Click bills through a per-surface merchant service, so which slug a deposit
#: uses decides which merchant is credited. The storefront sends ``click`` and
#: the mini app ``click_miniapp`` — but the slug arrives in the body while the
#: surface arrives in a header, and nothing tied them together: a web client
#: could route its deposit through the mini app's merchant just by asking.
#: Only the Click pair is surface-bound; every other acquirer is one merchant.
_SURFACE_BOUND: dict[str, str] = {
    "click": "web",
    "click_miniapp": "miniapp",
}

#: The merchant a caller gets when it does not say which surface it is. The
#: storefront's, because that is the one a stranger with a curl is least able
#: to misuse: it is where a web deposit belongs anyway.
_DEFAULT_CLICK_SLUG = "click"


def assert_provider_matches_surface(provider: str, source: str) -> None:
    """Refuse an acquirer slug that belongs to a different surface.

    ``X-Yupay-Surface`` is client-supplied and unauthenticated, so this is not
    a security boundary and cannot be made into one here — a caller who wants
    the other merchant can always claim to be the other surface. What it does
    is stop the *wrong* merchant being credited by accident, and stop the
    cheapest deliberate route to it.

    Which is why an unreadable header is not treated as permission. It used to
    be: ``normalise_source`` answers ``unknown`` for a missing or junk value,
    ``unknown`` was allowed for every slug, and so omitting the header entirely
    reached the mini app's merchant from anywhere — the very thing the check
    was added to stop, arrived at by not asking rather than by asking wrong.

    An unknown surface now gets the default merchant and nothing else. Money is
    never refused for want of a header: ``click`` stays available to any caller,
    and only the surface-specific slug needs its surface named.

    Raises:
        ValidationError: the slug names a surface this request did not.
    """
    required = _SURFACE_BOUND.get(provider)
    if required is None:
        return
    if source != required and not (source == "unknown" and provider == _DEFAULT_CLICK_SLUG):
        raise ValidationError(
            "this payment method belongs to another surface",
            extra={"provider": provider, "surface": source},
        )


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
