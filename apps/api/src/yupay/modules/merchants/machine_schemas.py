"""Pydantic DTOs for the machine API — the ``/merchant/v1`` wire contract.

These are a **third-party contract**: a reseller's server parses them and
nobody but its owner can redeploy it, so a field may be added but never
renamed, retyped or removed — that needs ``/merchant/v2``. They are
documented for integrators in this module's README, and they live apart from
``schemas.py`` (the admin SPA's DTOs, which we redeploy with the API) so the
difference in what a change costs is visible from the file name.

Money is ``Decimal`` end to end (AGENTS.md §9); Pydantic serialises it as a
JSON string, never a float.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

_CENT = Decimal("0.01")


def _cents_down(value: Decimal) -> Decimal:
    """Quantize a USD **balance** to two decimals, rounding down.

    Advertising more than a merchant holds means an order they were told they
    could afford fails with ``insufficient_deposit``.

    Args:
        value: The amount, at any scale.

    Returns:
        The amount at two decimal places, never rounded up.
    """
    return value.quantize(_CENT, rounding=ROUND_DOWN)


def _cents_up(value: Decimal) -> Decimal:
    """Quantize a USD **price** to two decimals, rounding up.

    The direction ``pricing.merchant_price`` already uses, and for its reason:
    rounding a price down erases margin a cent at a time, and would advertise
    below what the order path charges.

    Args:
        value: The amount, at any scale.

    Returns:
        The amount at two decimal places, never rounded down.
    """
    return value.quantize(_CENT, rounding=ROUND_CEILING)


# Money on ``/merchant/v1`` is a two-decimal JSON string: ``Decimal`` in
# Python, which Pydantic serialises as a string in JSON mode, never a float
# (IEEE-754 is how a price becomes ``1.0599999999999999`` on the merchant's
# side). The two-decimal step is needed regardless of rounding — the ledger's
# ``Numeric(20, 6)`` sum serialises as ``"42.500000"`` while an account with
# no postings at all serialises as ``"0"``, and a machine contract cannot hand
# a client two shapes for one quantity. Two annotations rather than one
# because the *direction* is a policy, and these two quantities need opposite
# ones; both are no-ops on today's values, and exist so that a widened quantum
# cannot make them silently agree on the wrong one.

#: A USD deposit balance on the wire.
UsdBalance = Annotated[Decimal, AfterValidator(_cents_down)]

#: A USD price on the wire.
UsdPrice = Annotated[Decimal, AfterValidator(_cents_up)]


class MerchantProfileOut(BaseModel):
    """Body of ``GET /merchant/v1/me`` — who is calling, and what they can spend.

    ``balance_usd`` is the deposit ledger's signed posting sum
    (``service.deposit_balance``), read live on every call — there is no
    balance column to drift from it.
    """

    merchant_id: str
    title: str
    status: str
    balance_usd: UsdBalance


class MerchantSkuOut(BaseModel):
    """One purchasable line of the wholesale price list.

    ``sku_id`` is what ``POST /merchant/v1/orders`` takes; ``price_usd`` is
    THIS merchant's price (``pricing.merchant_price``), not the retail one.
    ``updated_at`` is the SKU row's own stamp, so a merchant polling the
    price list can tell what moved (spec §8.4 — there are no price webhooks).
    """

    sku_id: str
    sku_code: str
    #: Human label: the SKU's denomination ("60 UC"), falling back to
    #: ``sku_code`` for lines that carry none. Denominations are stored
    #: untranslated, so unlike the brand and product names above it this is
    #: the same string in every locale.
    name: str
    price_usd: UsdPrice
    updated_at: datetime


class MerchantProductOut(BaseModel):
    """One product of a brand, with its purchasable SKUs.

    Only products with at least one purchasable SKU appear — there are no
    empty shells to iterate past. ``name`` is the catalog's default locale
    (``catalog.service.DEFAULT_LOCALE``, ``ru``); ``slug`` is the stable
    machine-readable half and never changes with a translation edit.
    """

    product_id: str
    slug: str
    name: str
    skus: list[MerchantSkuOut]


class MerchantBrandOut(BaseModel):
    """One brand of the wholesale catalog, with its products.

    ``name`` is the catalog's default locale, like the product's; a brand
    whose products all price out is absent entirely rather than empty.
    """

    brand_id: str
    slug: str
    name: str
    products: list[MerchantProductOut]


class MerchantCatalogOut(BaseModel):
    """Body of ``GET /merchant/v1/catalog``: the whole B2B price list.

    An object rather than a bare array so v1 clients keep parsing when a
    future field (a cursor, a generated-at stamp) is added beside ``brands``.
    """

    brands: list[MerchantBrandOut]


class MerchantOrderCreateIn(BaseModel):
    """Body of ``POST /merchant/v1/orders`` (spec §9.1).

    One SKU per order, deliberately: the spec's body shape has no ``qty`` and
    no line array, a reseller's own basket does not have to be ours, and a
    single line keeps "the order failed" from meaning "part of the order
    failed". A ``qty`` or an ``items`` array can be *added* later without a
    ``/merchant/v2`` — a new optional request field is additive; removing one
    is not.

    ``extra="forbid"`` on purpose. On a response, ignoring an unknown field is
    right; on a *request* it is how a typo'd ``fulfilment_data`` silently
    becomes an order with no player id, delivered to nobody.
    """

    model_config = ConfigDict(extra="forbid")

    #: The reseller's own id for this order, and the idempotency key (spec
    #: §9.3). Printable ASCII with no spaces, so it survives being a path
    #: segment in ``GET /merchant/v1/orders/{merchant_order_id}`` and the
    #: canonical signing string without an encoding argument.
    merchant_order_id: str = Field(min_length=1, max_length=128, pattern=r"^[\x21-\x7e]+$")
    #: From ``GET /merchant/v1/catalog``. Parsed as a UUID here rather than
    #: taken as free text: an unparseable id reaches Postgres as
    #: ``uuid = 'whatever'``, which is a ``DataError`` and a 500 where a clean
    #: refusal belongs.
    sku_id: str
    #: The price you last read from ``/catalog``. Within ±2% of ours the order
    #: executes at the **lower** of the two; outside it, ``422 price_changed``
    #: carries our current price (spec §8.4).
    expected_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    #: Whatever the SKU's product requires (a player id, a login). Validated
    #: against the same schema the storefront uses; unknown keys are dropped.
    fulfillment_data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sku_id")
    @classmethod
    def _is_a_uuid(cls, value: str) -> str:
        """Reject anything that is not a UUID, at the parse boundary."""
        try:
            UUID(value)
        except ValueError:
            raise ValueError("sku_id must be a UUID") from None
        return value


class MerchantOrderOut(BaseModel):
    """Body of ``POST /merchant/v1/orders``.

    ``status`` is the order's live status, not a fixed ``"paid"``: a merchant
    order is born paid and fulfilment starts in the same transaction, so what
    comes back is where that left it. Poll
    ``GET /merchant/v1/orders/{merchant_order_id}`` for the rest.
    """

    merchant_order_id: str
    #: Our id for the order. Quote it to support; key your own records on
    #: ``merchant_order_id``, which is yours and which we cannot change.
    order_id: str
    status: str
    sku_id: str
    #: What this order actually charged — after the ±2% rule, so it may be
    #: your ``expected_price`` rather than ours. Fixed from here on: whatever
    #: fulfilment ends up costing us is our problem, not yours (spec §8.4).
    price_usd: UsdPrice
    #: Your deposit after this order.
    balance_usd: UsdBalance
    created_at: datetime


__all__ = [
    "MerchantBrandOut",
    "MerchantCatalogOut",
    "MerchantOrderCreateIn",
    "MerchantOrderOut",
    "MerchantProductOut",
    "MerchantProfileOut",
    "MerchantSkuOut",
    "UsdBalance",
    "UsdPrice",
]
