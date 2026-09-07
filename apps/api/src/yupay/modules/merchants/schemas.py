"""Pydantic DTOs for the merchant B2B surfaces — admin, and the machine API.

Money is ``Decimal`` end to end (AGENTS.md §9); the generated TS client sees
strings. ``markup_pct`` bounds mirror the ``Numeric(5, 2)`` column — parsing,
not policy: the business guard against a fat-fingered markup is the order-time
margin floor (``pricing.violates_margin_floor``, spec §8.3), deliberately not
a schema rule here.

The ``/merchant/v1`` DTOs at the bottom are a **third-party contract**: a
reseller's server parses them and nobody but its owner can redeploy it, so a
field may be added but never renamed, retyped or removed — that needs
``/merchant/v2``. They are documented for integrators in this module's README.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

#: What ``Numeric(5, 2)`` can hold — the schema bound for markup fields.
_MARKUP_BOUND = Decimal("999.99")

_CENT = Decimal("0.01")


def _whole_cents(value: Decimal) -> Decimal:
    """Pin a USD amount to exactly two decimal places for the wire.

    Every value that reaches this is already a whole number of cents: prices
    come from ``pricing.merchant_price``, which rounds up to the cent, and
    ledger amounts are two-decimal by construction. So this is a *formatting*
    step, not a rounding policy — it exists because the ledger's
    ``Numeric(20, 6)`` sum serialises as ``"42.500000"`` while an
    account with no postings at all serialises as ``"0"``, and a machine
    contract cannot hand a client two shapes for the same quantity.

    ``ROUND_DOWN`` for the impossible case: if a sub-cent residue ever did
    appear, the balance we advertise must not exceed what the merchant can
    actually spend, or an order they were told they could afford fails with
    ``insufficient_deposit``.

    Args:
        value: The amount, at any scale.

    Returns:
        The same amount quantized to two decimal places.
    """
    return value.quantize(_CENT, rounding=ROUND_DOWN)


#: A USD amount on the wire: ``Decimal`` in Python, a two-decimal JSON string
#: out (Pydantic serialises ``Decimal`` as a string in JSON mode). Never a
#: float — IEEE-754 is how a price becomes ``1.0599999999999999`` on the
#: merchant's side.
UsdAmount = Annotated[Decimal, AfterValidator(_whole_cents)]


class MerchantCreateIn(BaseModel):
    """Body of ``POST /admin/merchants``."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _title_not_blank(self) -> MerchantCreateIn:
        """Reject whitespace-only titles at the parse boundary."""
        if not self.title.strip():
            raise ValueError("title must not be blank")
        return self


class MerchantOut(BaseModel):
    """One merchant row plus its USD deposit balance.

    The balance rides along on every merchant read — creation included, where
    it is trivially zero — so the admin SPA renders one shape everywhere.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: str
    created_at: datetime
    deposit_balance: Decimal


class MerchantListOut(BaseModel):
    """Body of ``GET /admin/merchants``."""

    items: list[MerchantOut]


class DepositCreditIn(BaseModel):
    """Body of ``POST /admin/merchants/{id}/deposit-credits``."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    note: str | None = Field(default=None, max_length=512)


class DepositCreditOut(BaseModel):
    """Result of a deposit credit.

    ``amount`` is the amount the returned ledger transaction actually booked —
    on an idempotent replay that is the ORIGINAL amount, not the request's.
    The ledger replays by key without comparing parameters, so this field is
    what makes a mismatched replay visible to the admin UI.
    """

    transaction_id: str
    merchant_id: str
    amount: Decimal
    balance: Decimal


class MerchantTxnOut(BaseModel):
    """One ledger movement of a merchant's USD deposit.

    ``amount`` is the signed deposit delta: positive means the balance went
    up (a credit), negative means it went down (an M2 order charge). ``note``
    is the operator's free text from the credit; ``actor`` the
    ``admin:<id>`` who booked it.
    """

    transaction_id: str
    kind: str
    amount: Decimal
    note: str | None
    actor: str | None
    created_at: datetime


class MerchantTxnListOut(BaseModel):
    """Body of ``GET /admin/merchants/{id}/transactions``, newest first."""

    items: list[MerchantTxnOut]


class ApiKeyCreateIn(BaseModel):
    """Body of ``POST /admin/merchants/{id}/api-keys``; every field optional."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(default="", max_length=64)
    #: Addresses or CIDR blocks allowed to use the key; ``None``/omitted means
    #: no filter. Bounded at 32 entries because ``auth.address_allowed`` walks
    #: the list on every machine-API request.
    ip_allowlist: list[str] | None = Field(default=None, max_length=32)

    @field_validator("ip_allowlist")
    @classmethod
    def _entries_parse(cls, value: list[str] | None) -> list[str] | None:
        """Reject anything ``ipaddress`` cannot read, at the parse boundary.

        A typo'd entry stored verbatim would silently never match and lock the
        merchant out of their own API with a 403 nobody can explain. Host bits
        are allowed (``203.0.113.5/24``) and read as the network at match
        time, the same ``strict=False`` the auth path uses.
        """
        if value is None:
            return None
        cleaned: list[str] = []
        for raw in value:
            entry = raw.strip()
            try:
                ipaddress.ip_network(entry, strict=False)
            except ValueError:
                raise ValueError(f"not an IP address or CIDR block: {entry!r}") from None
            cleaned.append(entry)
        return cleaned or None


class ApiKeyOut(BaseModel):
    """One machine credential, as the admin surface sees it.

    There is deliberately no ``secret`` field: the secret exists only in the
    response to the call that minted it (:class:`ApiKeyCreatedOut`), and this
    is the shape every read returns.
    """

    model_config = ConfigDict(from_attributes=True)

    key_id: str
    label: str
    ip_allowlist: list[str] | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyListOut(BaseModel):
    """Body of ``GET /admin/merchants/{id}/api-keys``, newest first."""

    items: list[ApiKeyOut]


class ApiKeyCreatedOut(ApiKeyOut):
    """Result of minting a key — the ONLY response that ever carries a secret.

    ``secret`` is ``None`` on an idempotent replay. The replay snapshot is
    stored in ``idempotent_responses``, a table with no reaper, and a usable
    credential sitting there in the clear forever is worse than making a
    retry after a lost response say so: revoke the key and issue another.
    """

    secret: str | None


class SkuB2bPatchIn(BaseModel):
    """Body of ``PATCH /admin/catalog/skus/{id}/b2b``; absent fields stay untouched."""

    model_config = ConfigDict(extra="forbid")

    markup_pct: Decimal | None = Field(
        default=None, ge=-_MARKUP_BOUND, le=_MARKUP_BOUND, decimal_places=2
    )
    visible_b2b: bool | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> SkuB2bPatchIn:
        """An empty patch is a client bug, not a no-op success."""
        if self.markup_pct is None and self.visible_b2b is None:
            raise ValueError("provide markup_pct and/or visible_b2b")
        return self


class SkuB2bOut(BaseModel):
    """The B2B slice of a SKU after a patch."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    sku_code: str
    b2b_markup_pct: Decimal
    visible_b2b: bool


class BulkMarkupIn(BaseModel):
    """Body of ``POST /admin/catalog/b2b/bulk-markup``: exactly one target."""

    model_config = ConfigDict(extra="forbid")

    brand_slug: str | None = Field(default=None, min_length=1, max_length=64)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    markup_pct: Decimal = Field(ge=-_MARKUP_BOUND, le=_MARKUP_BOUND, decimal_places=2)

    @model_validator(mode="after")
    def _exactly_one_target(self) -> BulkMarkupIn:
        """One brand or one category — never both, never neither."""
        if (self.brand_slug is None) == (self.category is None):
            raise ValueError("provide exactly one of brand_slug or category")
        return self


class BulkMarkupOut(BaseModel):
    """How many SKUs the bulk update touched."""

    affected: int


class BrandB2bPatchIn(BaseModel):
    """Body of ``PATCH /admin/catalog/brands/{id}/b2b``."""

    model_config = ConfigDict(extra="forbid")

    visible_b2b: bool


class BrandB2bOut(BaseModel):
    """The B2B slice of a brand after a patch."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    visible_b2b: bool


# --- the machine API (/merchant/v1) -----------------------------------------
#
# Third-party contract. See the module docstring: additive changes only.


class MerchantProfileOut(BaseModel):
    """Body of ``GET /merchant/v1/me`` — who is calling, and what they can spend.

    ``balance_usd`` is the deposit ledger's signed posting sum
    (``service.deposit_balance``), read live on every call — there is no
    balance column to drift from it.
    """

    merchant_id: str
    title: str
    status: str
    balance_usd: UsdAmount


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
    price_usd: UsdAmount
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


__all__ = [
    "ApiKeyCreateIn",
    "ApiKeyCreatedOut",
    "ApiKeyListOut",
    "ApiKeyOut",
    "BrandB2bOut",
    "BrandB2bPatchIn",
    "BulkMarkupIn",
    "BulkMarkupOut",
    "DepositCreditIn",
    "DepositCreditOut",
    "MerchantBrandOut",
    "MerchantCatalogOut",
    "MerchantCreateIn",
    "MerchantListOut",
    "MerchantOut",
    "MerchantProductOut",
    "MerchantProfileOut",
    "MerchantSkuOut",
    "MerchantTxnListOut",
    "MerchantTxnOut",
    "SkuB2bOut",
    "SkuB2bPatchIn",
    "UsdAmount",
]
