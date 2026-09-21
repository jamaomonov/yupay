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

from datetime import datetime
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from yupay.modules.merchants.allowlist import MAX_ENTRIES, normalize_allowlist
from yupay.modules.merchants.models import WEBHOOK_URL_MAX

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
    #: Percentage POINTS added to every SKU's ``b2b_markup_pct`` for this
    #: merchant, or ``None`` for the catalogue price everyone else pays.
    #: Negative is the ordinary case — a negotiated rate for volume.
    markup_adjustment_pp: Decimal | None = None


class MerchantListOut(BaseModel):
    """Body of ``GET /admin/merchants``."""

    items: list[MerchantOut]


class MerchantMarkupPatchIn(BaseModel):
    """Body of ``PATCH /admin/merchants/{id}/markup``.

    Percentage **points**, added to each SKU's own ``b2b_markup_pct`` — not a
    multiplier and not a price. With the catalogue at 7 %, ``-2`` prices that
    merchant at 5 % over cost, on everything.

    ``None`` clears the adjustment back to the catalogue price. It is a
    distinct value from ``0``, which is an operator saying "no discount" out
    loud; both compute the same price and only one of them records a decision.

    The range is the column's (``Numeric(5, 2)``) and is deliberately wider
    than anything sensible: what makes a value safe is the margin floor, not
    an arbitrary cap, and that check needs the catalogue rather than a
    validator.
    """

    model_config = ConfigDict(extra="forbid")

    markup_adjustment_pp: Decimal | None = Field(
        default=None,
        ge=Decimal("-999.99"),
        le=Decimal("999.99"),
        decimal_places=2,
        description=(
            "Percentage points added to every SKU's markup for this merchant. "
            "Negative for a negotiated discount; `null` restores the catalogue price."
        ),
    )


class DepositCreditIn(BaseModel):
    """Body of ``POST /admin/merchants/{id}/deposit-credits``."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    note: str | None = Field(default=None, max_length=512)
    #: The order this credit settles, if it settles one — our order id, the
    #: ``order_id`` the merchant's own order read returns, not their
    #: ``merchant_order_id``. Optional and additive: omitted, the credit is the
    #: ordinary prepayment it always was. Given, it must be an order of **this**
    #: merchant's, and the amount shows up on that order's ``refunded_usd``.
    #:
    #: Bounded to the ledger's ``reference_id`` column rather than to 36
    #: characters, and the shape is checked in ``deposit`` and not here: an id
    #: that cannot be an order id is an order that is not there, and it answers
    #: the same 404 as one belonging to somebody else. A 422 for the malformed
    #: case would put the shape of the id back into the answer.
    order_id: str | None = Field(default=None, max_length=64)


class DepositCreditOut(BaseModel):
    """Result of a deposit credit.

    ``amount`` and ``order_id`` are both read off the returned ledger
    transaction — on an idempotent replay those are the ORIGINAL call's, not
    this request's. The ledger replays by key without comparing parameters, so
    these two fields are what make a mismatched replay visible to the admin UI
    instead of silently doing nothing.
    """

    transaction_id: str
    merchant_id: str
    amount: Decimal
    balance: Decimal
    #: The order this transaction is booked against, or ``null`` for a plain
    #: prepayment.
    order_id: str | None = None


class DepositDebitIn(BaseModel):
    """Body of ``POST /admin/merchants/{id}/deposit-debits``."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    #: Required, unlike the credit's optional ``note``. A debit is the only
    #: movement whose justification lives entirely outside the system — no
    #: order, no supplier outcome, no payment — so this string is the only
    #: record of why the balance dropped, and an operator who cannot name a
    #: reason is one who should not be taking the money.
    reason: str = Field(min_length=1, max_length=512)


class DepositDebitOut(BaseModel):
    """Result of a deposit debit.

    ``amount`` is read off the returned ledger transaction, so on an
    idempotent replay it is the ORIGINAL call's and not this request's — the
    same reason ``DepositCreditOut`` echoes its own back. There is no
    ``order_id``: a debit is booked against the merchant, never an order, or
    it would land on that order's ``refunded_usd`` as money the merchant
    never got back.
    """

    transaction_id: str
    merchant_id: str
    amount: Decimal
    balance: Decimal


class MerchantTxnOut(BaseModel):
    """One ledger movement of a merchant's USD deposit.

    ``amount`` is the signed deposit delta: positive means the balance went
    up (a credit or a refund), negative means it went down — an M2 order
    charge, or an operator's correction (``merchant_deposit_debit``). The
    sign comes from the posting's direction, so a new movement needs no
    change here; ``kind`` is what tells the two apart. ``note`` is the
    operator's free text — the credit's ``note`` or the debit's ``reason``;
    ``actor`` the ``admin:<id>`` who booked it.
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
    ip_allowlist: list[str] | None = Field(default=None, max_length=MAX_ENTRIES)

    #: Shared with the cabinet's own create DTO rather than re-derived: two
    #: tables of what an address is would drift, and the drift is silent.
    _entries_parse = field_validator("ip_allowlist")(normalize_allowlist)


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


class WebhookSetIn(BaseModel):
    """Body of ``PUT /admin/merchants/{id}/webhook``.

    Only shape is checked here. The SSRF rules (https, no private/loopback
    literals) live in ``admin.validate_webhook_url`` so that every caller of
    the facade gets them — including M4's cabinet, which will not reuse this
    DTO — rather than only the requests that happen to arrive through this
    schema.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=WEBHOOK_URL_MAX)


class WebhookOut(BaseModel):
    """A merchant's webhook configuration, as every read returns it.

    There is deliberately no ``secret`` field: the secret exists only in the
    response to the call that minted it (:class:`WebhookSecretOut`).
    ``failure_streak`` and the two timestamps are the delivery worker's
    running state — an operator answering "is this hook healthy" reads them
    here rather than counting rows in the delivery log.
    """

    model_config = ConfigDict(from_attributes=True)

    merchant_id: str
    url: str
    disabled_at: datetime | None
    failure_streak: int
    last_success_at: datetime | None
    last_failure_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WebhookSecretOut(WebhookOut):
    """The response of the two calls that can mint a secret — the only ones carrying it.

    ``secret`` is ``None`` when the call did not mint one: a URL change or a
    re-enable on an existing hook, and every idempotent replay. The replay
    snapshot lives in ``idempotent_responses``, a table with no reaper, and a
    usable signing key sitting there forever is worse than telling an
    operator whose first response was lost to rotate and take the new one.
    """

    secret: str | None


class MerchantUserOut(BaseModel):
    """One person who can sign into a reseller's cabinet.

    Carries ``email``, which is PII: this shape is returned on an admin route
    and nowhere else, and nothing here is ever logged — the same rule
    ``users.email`` already lives under (``docs/security/pii-handling.md``).

    ``last_login_at`` is **derived**, not stored: the newest row in
    ``merchant_sessions`` for this person, whose ``created_at`` is written at
    sign-in. ``None`` means they have never got in, which is the first thing
    worth knowing when somebody says they cannot — and it is a different
    answer from "signed in last month and cannot now".

    There is deliberately no field for the password hash, the session tokens
    or anything else that could be replayed.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    email_confirmed_at: datetime | None
    last_login_at: datetime | None
    timezone: str
    offer_version: str | None
    offer_accepted_at: datetime | None
    created_at: datetime


class MerchantUserListOut(BaseModel):
    """Body of ``GET /admin/merchants/{id}/users``, oldest first.

    Oldest first, unlike every other list on this surface: the first operator
    is the one who registered the account, and on an account with two people
    that is the one support is usually asking about.
    """

    items: list[MerchantUserOut]


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
    "WebhookOut",
    "WebhookSecretOut",
    "WebhookSetIn",
]
