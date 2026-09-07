"""Pydantic DTOs for the merchant B2B **admin** surface.

Money is ``Decimal`` end to end (AGENTS.md §9); the generated TS client sees
strings. ``markup_pct`` bounds mirror the ``Numeric(5, 2)`` column — parsing,
not policy: the business guard against a fat-fingered markup is the order-time
margin floor (``pricing.violates_margin_floor``, spec §8.3), deliberately not
a schema rule here.

The ``/merchant/v1`` wire contract lives in ``machine_schemas.py``, not here.
These DTOs ship with the admin SPA and change with it; those are parsed by a
reseller's server that nobody but its owner can redeploy, so a change to one
of them costs a ``/merchant/v2``. The two are kept apart so that difference is
visible from the file name.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

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
    "MerchantCreateIn",
    "MerchantListOut",
    "MerchantOut",
    "MerchantTxnListOut",
    "MerchantTxnOut",
    "SkuB2bOut",
    "SkuB2bPatchIn",
]
