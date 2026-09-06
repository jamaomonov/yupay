"""Pydantic DTOs for the merchant B2B admin surface.

Money is ``Decimal`` end to end (AGENTS.md §9); the generated TS client sees
strings. ``markup_pct`` bounds mirror the ``Numeric(5, 2)`` column — parsing,
not policy: the business guard against a fat-fingered markup is the order-time
margin floor (``pricing.violates_margin_floor``, spec §8.3), deliberately not
a schema rule here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: What ``Numeric(5, 2)`` can hold — the schema bound for markup fields.
_MARKUP_BOUND = Decimal("999.99")


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


__all__ = [
    "BrandB2bOut",
    "BrandB2bPatchIn",
    "BulkMarkupIn",
    "BulkMarkupOut",
    "DepositCreditIn",
    "DepositCreditOut",
    "MerchantCreateIn",
    "MerchantListOut",
    "MerchantOut",
    "MerchantTxnListOut",
    "MerchantTxnOut",
    "SkuB2bOut",
    "SkuB2bPatchIn",
]
