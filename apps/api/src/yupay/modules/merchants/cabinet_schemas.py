"""Request and response bodies for the merchant cabinet.

Separate from ``machine_schemas`` on purpose. That file is a **frozen
third-party contract** a reseller's server is written against; this one serves
our own browser and may change with the app that reads it. Sharing them would
make every cabinet tweak a breaking API change.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from yupay.modules.merchants.allowlist import MAX_ENTRIES, normalize_allowlist
from yupay.modules.merchants.machine_schemas import UsdAmount, UsdBalance
from yupay.modules.merchants.models import WEBHOOK_URL_MAX

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


class CabinetProfilePatchIn(BaseModel):
    """Body of ``PATCH /merchant/cabinet/me``. Display settings only.

    Nothing here changes what the API says or does: ``timezone`` decides when
    we mail this operator, and the cabinet renders timestamps in the viewer's
    own zone regardless. The API always speaks ISO 8601 UTC (spec §11), and a
    setting that looked like it changed that would be the worse feature.
    """

    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def _loadable(cls, value: str) -> str:
        """An IANA name the running system can actually load.

        Checked by loading it rather than against a hard-coded list: the list
        the cabinet offers is a convenience, and a tzdata update that adds a
        zone should not need a code change here to accept it.
        """
        name = value.strip()
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"not a known IANA timezone: {name!r}") from None
        return name


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
    #: Addresses or CIDR blocks allowed to use this key; ``null`` means no
    #: filter. There is no endpoint that edits it — narrowing a live key's
    #: allowlist is a rotation, so that a mistake is recoverable by deploying
    #: the key you still hold rather than by a support call.
    ip_allowlist: list[str] | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class CabinetApiKeyCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: What this key is for, in the operator's own words ("staging", "billing
    #: box"). Rotation is "issue, deploy, revoke", and a label is how a person
    #: tells two live keys apart while both are.
    label: str = Field(default="", max_length=64)
    #: Optional. Same field, same rules and the **same validator** as the
    #: admin surface's — two tables of what an address is would drift, and an
    #: entry we accept but ``auth.address_allowed`` cannot match locks a
    #: merchant out of their own API with a 403 nobody can explain.
    ip_allowlist: list[str] | None = Field(default=None, max_length=MAX_ENTRIES)

    _entries_parse = field_validator("ip_allowlist")(normalize_allowlist)


class CabinetIssuedKeyOut(BaseModel):
    """The one moment the secret exists outside our encryption."""

    key_id: str
    secret: str
    label: str
    ip_allowlist: list[str] | None
    created_at: datetime


class CabinetWebhookSetIn(BaseModel):
    """Body of ``PUT /merchant/cabinet/webhook``.

    Shape only. The SSRF rules — https, no private or loopback host — live in
    ``admin.validate_webhook_url``, which ``set_webhook`` applies for every
    caller of the facade. That placement is what lets a **merchant** aim our
    outbound worker at an address of their choosing without the rules having
    to be restated here, and restating them is how one copy drifts.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=WEBHOOK_URL_MAX)


class CabinetWebhookOut(BaseModel):
    """The endpoint and how it has been behaving.

    No ``merchant_id``: the cabinet already knows whose it is, and a field
    naming the account on every response is a field a future screen might
    read a request parameter into. No ``secret`` either — that exists only in
    the response to the call that minted it.

    ``failure_streak`` and the two timestamps are the delivery worker's
    running state. A reseller asking "is my hook healthy" reads them here
    rather than counting rows in the log below.
    """

    model_config = ConfigDict(from_attributes=True)

    url: str
    disabled_at: datetime | None
    failure_streak: int
    last_success_at: datetime | None
    last_failure_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CabinetWebhookSecretOut(CabinetWebhookOut):
    """The two calls that can mint a signing secret — the only ones carrying it.

    ``secret`` is ``None`` when the call minted nothing: a URL change on an
    existing hook, or a re-enable. Changing where deliveries go must not
    silently break a working verifier, so it does not rotate the key.
    """

    secret: str | None


class CabinetDeliveryRowOut(BaseModel):
    """One attempted delivery, as the log shows it.

    ``url`` is the address the attempt went to, snapshotted at enqueue rather
    than joined from the configuration — the question this log answers turns
    on which host answered, not on which host is configured now.

    ``payload`` is exactly the body we signed and sent, so a reseller can
    replay our signature against it. ``response_body`` and ``last_error`` are
    bounded in their columns, not merely by the writer, because both
    interpolate text a third party chose and both are rendered in a browser.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    url: str
    status: str
    attempts_count: int
    payload: dict[str, Any]
    response_code: int | None
    response_body: str | None
    last_error: str | None
    next_attempt_at: datetime
    created_at: datetime
    updated_at: datetime


class CabinetDeliveriesOut(BaseModel):
    items: list[CabinetDeliveryRowOut]
    #: Keyset, like every other page on this surface: the worker writes this
    #: log while a person reads it.
    next_cursor: str | None


__all__ = [
    "CabinetApiKeyCreateIn",
    "CabinetApiKeyOut",
    "CabinetConfirmIn",
    "CabinetDeliveriesOut",
    "CabinetDeliveryRowOut",
    "CabinetIssuedKeyOut",
    "CabinetLoginIn",
    "CabinetOrderIn",
    "CabinetOrderRowOut",
    "CabinetOrdersOut",
    "CabinetProfileOut",
    "CabinetProfilePatchIn",
    "CabinetRegisterIn",
    "CabinetTokenIn",
    "CabinetTokensOut",
    "CabinetWebhookOut",
    "CabinetWebhookSecretOut",
    "CabinetWebhookSetIn",
]
