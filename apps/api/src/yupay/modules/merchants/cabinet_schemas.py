"""Request and response bodies for the merchant cabinet.

Separate from ``machine_schemas`` on purpose. That file is a **frozen
third-party contract** a reseller's server is written against; this one serves
our own browser and may change with the app that reads it. Sharing them would
make every cabinet tweak a breaking API change.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from yupay.modules.merchants.machine_schemas import UsdAmount, UsdBalance

#: Long enough to resist a guess, short enough that a real person will use a
#: manager rather than fight the field. Matches the storefront's floor.
_MIN_PASSWORD = 10


class CabinetRegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=_MIN_PASSWORD, max_length=128)
    #: The company name. Shown in admin beside their orders and on their own
    #: dashboard; not validated beyond length, because a legal name is not
    #: something a regex knows about.
    title: str = Field(min_length=2, max_length=128)
    #: Must be ``True``. A checkbox that can be omitted is a checkbox nobody
    #: ticked, and the whole point of the record is that they did.
    accept_offer: bool

    @field_validator("accept_offer")
    @classmethod
    def _must_accept(cls, value: bool) -> bool:
        if not value:
            raise ValueError("the B2B offer must be accepted to register")
        return value


class CabinetLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class CabinetTokenIn(BaseModel):
    """A refresh or logout body. One field, named for what it carries."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=256)


class CabinetConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=4096)


class CabinetTokensOut(BaseModel):
    """What the browser stores after a sign-in or a rotation."""

    access_token: str
    refresh_token: str
    expires_in: int


class CabinetProfileOut(BaseModel):
    """``GET /merchant/cabinet/me`` — the operator and their company."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    email: str
    timezone: str
    merchant_id: str
    title: str
    status: str
    #: Live deposit balance. ``UsdBalance`` from the machine schemas, not a
    #: bare ``Decimal``: the ledger's ``Numeric(20, 6)`` serialises as
    #: ``"42.500000"`` while an account with no postings at all serialises as
    #: ``"0"``, and a cabinet that renders a balance two ways on two screens is
    #: the same bug as an API that does. The **value type** is shared while the
    #: DTOs stay separate — a rounding rule copied is a rounding rule that
    #: drifts, and the direction here is policy: never advertise more than a
    #: merchant holds.
    balance_usd: UsdBalance
    #: Which offer version they accepted, and when. Shown in Settings so an
    #: operator can see what they agreed to without asking support.
    offer_version: str | None
    offer_accepted_at: datetime | None


class CabinetOrderIn(BaseModel):
    """Ordering from the catalog page, without a ``merchant_order_id``.

    The cabinet mints one (``manual-<uuid>``, spec §11) rather than asking a
    person to invent an idempotency key. Everything else is the machine API's
    body, because this order must walk the identical pricing, validation and
    deposit path — one flow, so a cabinet order and an API order are the same
    kind of thing in history, in the ledger and in a dispute.
    """

    model_config = ConfigDict(extra="forbid")

    sku_id: str
    quantity: int | None = None
    amount_usd: Decimal | None = None
    expected_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    fulfillment_data: dict[str, str] = Field(default_factory=dict)


class CabinetOrderRowOut(BaseModel):
    """One line of the Orders list.

    Money comes from the ledger, not from the order line: two of the three SKU
    shapes put a per-unit rate or a face value there and the money elsewhere,
    so a list built off the line would show $0.016537 against an order that
    cost $16.54.
    """

    merchant_order_id: str
    order_id: str
    status: str
    sku_code: str
    price_usd: UsdAmount
    refunded_usd: UsdAmount
    created_at: datetime
    delivered_at: datetime | None


class CabinetOrdersOut(BaseModel):
    items: list[CabinetOrderRowOut]
    #: Present only while older rows remain. Keyset, not an offset: an offset
    #: page shifts under a merchant whose orders keep arriving.
    next_cursor: str | None


class CabinetApiKeyOut(BaseModel):
    """One machine credential, as Settings lists it.

    Never carries the secret. That is returned once, by the create call, and
    is not stored in a readable form afterwards — so a list that could show it
    would mean we had kept it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    key_id: str
    label: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class CabinetApiKeyCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: What this key is for, in the operator's own words ("staging", "billing
    #: box"). Rotation is "issue, deploy, revoke", and a label is how a person
    #: tells two live keys apart while both are.
    label: str = Field(default="", max_length=64)


class CabinetIssuedKeyOut(BaseModel):
    """The one moment the secret exists outside our encryption."""

    key_id: str
    secret: str
    label: str
    created_at: datetime


__all__ = [
    "CabinetApiKeyCreateIn",
    "CabinetApiKeyOut",
    "CabinetConfirmIn",
    "CabinetIssuedKeyOut",
    "CabinetLoginIn",
    "CabinetOrderIn",
    "CabinetOrderRowOut",
    "CabinetOrdersOut",
    "CabinetProfileOut",
    "CabinetRegisterIn",
    "CabinetTokenIn",
    "CabinetTokensOut",
]
