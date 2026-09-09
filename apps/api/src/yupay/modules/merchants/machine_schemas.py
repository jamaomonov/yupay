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
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

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


def _cents(value: Decimal) -> Decimal:
    """Quantize a USD **ledger amount** to two decimals, without a direction.

    A balance is rounded so we never advertise more than a merchant holds, and
    a price so we never advertise less than we charge. A ledger line is
    neither: it is a statement of something that already happened, and the
    property that matters is that the column adds up to the balance — which a
    directional rounding would break as soon as it moved a value. Every amount
    on this ledger is a whole cent by construction (credits are two-decimal by
    schema, charges are ``pricing.merchant_price``'s ceil-to-cent), so this is
    a no-op today; it exists because ``Numeric(20, 6)`` serialises as
    ``"1.070000"`` and a machine contract cannot hand a client two shapes for
    one quantity.

    Args:
        value: The amount, at any scale. May be negative.

    Returns:
        The amount at two decimal places.
    """
    return value.quantize(_CENT)


#: A signed USD ledger amount, or a total of them, on the wire.
UsdAmount = Annotated[Decimal, AfterValidator(_cents)]


def _canonical_uuid(value: str) -> str:
    """Parse an id as a UUID and return **Postgres'** spelling of it.

    ``str(UUID(value))`` and not ``value``, which is the whole point.
    ``UUID()`` accepts four spellings of the same id — plain, braced
    (``{0198…}``), undashed, and ``urn:uuid:0198…`` — and Postgres' ``uuid``
    type accepts only the first two of those four. Returning the caller's
    original string therefore validated an id and then handed the database one
    it refuses: ``where(Sku.id == "{0198…}")`` raised ``DataError``, nothing
    handles ``DBAPIError``, and the caller got Starlette's plain-text **500**
    from a schema whose entire job was to prevent exactly that.

    That is not a hypothetical spelling. ``Guid.ToString("B")`` in .NET is
    braced, and our own README tells integrators a 500 is safe to retry — so
    the failure mode was a client retrying forever against an endpoint that can
    never accept its ids.

    Args:
        value: The id as sent.

    Returns:
        The canonical, dashed, unbraced lowercase form.

    Raises:
        ValueError: It is not a UUID in any spelling. The message names the
            field rather than being generic because the published error example
            in the module README quotes it verbatim, and both fields carrying
            this annotation are called ``sku_id``.
    """
    try:
        return str(UUID(value))
    except ValueError:
        raise ValueError("sku_id must be a UUID") from None


#: A catalog id on the wire: parsed as a UUID at the boundary and normalised to
#: the one spelling Postgres accepts. One annotation shared by every id field on
#: this contract — the order body's and the validate body's — because a second
#: copy of the parse is a second chance to return the unnormalised string.
SkuId = Annotated[str, AfterValidator(_canonical_uuid)]


class MerchantValidationProblem(BaseModel):
    """The ``422`` a request the schema itself refused answers with.

    Not raised anywhere — it exists so the OpenAPI document tells the truth for
    this prefix. Every other surface answers a validation failure with
    FastAPI's ``HTTPValidationError`` (``{"detail": [ … ]}``); ``/merchant/v1``
    answers RFC 7807, because its error table is published to third parties
    who cannot redeploy on our schedule. The renderer is
    ``core.errors.problem_json_validation_handler``, which is scoped to this
    prefix for that reason and delegates everywhere else.

    ``detail`` is a **string** here, as RFC 7807 requires and as every other
    error on this API already is; the per-field list FastAPI would have put
    there rides in ``errors`` instead.
    """

    type: str
    title: str
    status: int
    detail: str
    #: Always ``core.errors.CODE_INVALID_REQUEST``. A field rather than a
    #: constant on the wire so a client switching on ``code`` needs no special
    #: case for this one.
    code: str
    #: FastAPI's own per-failure entries — ``{type, loc, msg, input, ctx}`` —
    #: passed through unchanged. Read them for diagnostics; do not switch on
    #: them, they are a framework's shape and not part of this contract.
    errors: list[dict[str, Any]]


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
    #: taken as free text — an unparseable id reaches Postgres as
    #: ``uuid = 'whatever'``, which is a ``DataError`` and a 500 where a clean
    #: refusal belongs — and normalised to the spelling Postgres accepts; see
    #: :func:`_canonical_uuid`.
    sku_id: SkuId
    #: The price you last read from ``/catalog``. A tolerance, not a bid:
    #: within ±2% of ours the order proceeds and is charged at **our** current
    #: price; outside it, ``422 price_changed`` carries that price (spec §8.4,
    #: amended 2026-09-07).
    expected_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    #: Whatever the SKU's product requires (a player id, a login). Validated
    #: against the same schema the storefront uses
    #: (``orders.validation.validate_fulfillment_data``), which **rejects** a
    #: key the product does not declare rather than dropping it — so a SKU that
    #: requires nothing accepts only ``{}``. The README says so at the field.
    fulfillment_data: dict[str, Any] = Field(default_factory=dict)


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
    #: What this order actually charged — always **our** price at the moment
    #: you ordered, which is within ±2% of the ``expected_price`` you sent or
    #: the order would have been refused. Fixed from here on: whatever
    #: fulfilment ends up costing us is our problem, not yours (spec §8.4).
    price_usd: UsdPrice
    #: Your deposit after this order.
    balance_usd: UsdBalance
    created_at: datetime


class MerchantOrderEventOut(BaseModel):
    """One entry of an order's timeline.

    ``event`` only — no payload. An ``order_events`` payload carries internal
    values (``order.paid``'s is a fingerprint of the reseller's own request;
    ``order.failed``'s is an operator's free-text note when support closed the
    order by hand, and an internal label when the automatic refund closed it —
    M3c Task 6), and none of them is worth a field on a third-party contract.
    """

    #: One of the ``order.*`` kinds listed in the module README. Kinds outside
    #: that list — internal audit rows such as ``admin.deliveries_viewed`` —
    #: are omitted, and a new kind stays omitted until it is added there.
    event: str
    at: datetime


class MerchantDeliveryOut(BaseModel):
    """The artifact a delivered order handed over — the voucher code lives here.

    Present as soon as a ``deliveries`` row exists for the order — it is the
    delivery record that decides, not the order's status, which is what
    ``order_status._delivery`` reads. The two normally move together.
    ``artifact``'s shape depends on ``artifact_kind`` (``voucher_code`` or
    ``topup_receipt`` today); for ``voucher_code`` it carries ``code`` (or
    ``codes``). Internal fields recorded alongside it — our supplier's name,
    their order id, our warehouse row — are filtered out by
    ``fulfillment.buyer_safe_artifact``, the same allow-list the storefront
    uses.
    """

    artifact_kind: str
    artifact: dict[str, Any]
    delivered_at: datetime


class MerchantOrderStatusOut(BaseModel):
    """Body of ``GET /merchant/v1/orders/{merchant_order_id}``.

    The reseller's whole view of one order: where it is, what it cost, what it
    delivered, and whether anything came back. **This is the only place the
    delivered voucher code is handed over** — the ``order.status_changed``
    webhook (M3a, ADR-0070) does not carry it, because a webhook body lands in
    the merchant's logs and in ours, and a voucher code is a bearer instrument.
    """

    merchant_order_id: str
    #: Our id for the order. Quote it to support; key your own records on
    #: ``merchant_order_id``, which is yours and which we cannot change.
    order_id: str
    #: ``paid`` → ``fulfilling`` → ``delivered``, or ``failed``. ``failed``
    #: arrives two ways: support closing an undeliverable order by hand, and —
    #: since M3c Task 6 — a delivery failure whose **whole** charge is already
    #: back on the deposit, which closes itself within seconds. Read
    #: ``failure_reason`` to tell them apart. New values may be added; treat one
    #: you do not know as still in flight, which is why the refund reuses
    #: ``failed`` instead of minting ``refunded``.
    status: str
    sku_id: str
    #: What this order charged. Final — see ``POST /merchant/v1/orders``.
    price_usd: UsdPrice
    #: How much of ``price_usd`` has been credited back to your deposit.
    #: ``"0.00"`` until something has come back; read from the ledger, not a
    #: flag, so both routes land here — M3b's automatic refund of a supplier
    #: failure that returned our money, and a settlement support books by
    #: hand. Never more than ``price_usd``: both writers refuse to take an
    #: order past its own charge.
    refunded_usd: UsdAmount
    created_at: datetime
    paid_at: datetime | None
    delivered_at: datetime | None
    #: ``null``, ``"fulfillment_delayed"``, ``"fulfillment_failed_refunded"``,
    #: ``"fulfillment_failed"`` or ``"order_failed"`` — a closed vocabulary,
    #: additive only. Never an operator's or a supplier's own words: those are
    #: internal, and a client cannot switch on prose.
    #:
    #: **``"fulfillment_delayed"`` is the one value that is not terminal**
    #: (M3b Task 4). It means the delivery has stopped but the order has not:
    #: keep polling, do not re-order, do not refund your end customer. Every
    #: other non-null value means stop. A loop that breaks on
    #: ``failure_reason != null`` stops polling an order we are about to
    #: deliver — see the module README.
    #:
    #: ``"fulfillment_failed_refunded"`` is M3b Task 3's addition and means
    #: "the delivery failed **and all** of what you paid is back"; a *partial*
    #: settlement is a human mid-decision and reads ``"fulfillment_failed"``.
    #:
    #: No value here says **which supplier** or **what went wrong with them**:
    #: not whether one kept our money versus we cannot tell (both read
    #: ``"fulfillment_failed"``), and not that a delay is our own balance
    #: running short. Those are facts about our supplier relationships rather
    #: than about your order.
    failure_reason: str | None
    delivery: MerchantDeliveryOut | None
    timeline: list[MerchantOrderEventOut]


class MerchantPlayerCheckIn(BaseModel):
    """Body of ``POST /merchant/v1/validate/player`` (spec §9.1).

    ``extra="forbid"``, for the same reason ``MerchantOrderCreateIn`` sets it:
    on a request, silently ignoring an unknown key is how a typo'd
    ``player_id`` becomes a check of nothing that answers ``unsupported`` and
    gets read as "this SKU needs no verification".
    """

    model_config = ConfigDict(extra="forbid")

    #: The SKU you are about to order, from ``GET /merchant/v1/catalog``. A
    #: SKU, not a product, so the id you check is the id you buy. Same
    #: :data:`SkuId` the order body uses: parsed as a UUID at the boundary and
    #: normalised to the spelling Postgres accepts.
    sku_id: SkuId
    #: Your **end customer's** identifier: the game's player id, or the Steam
    #: login for a Steam top-up. We hold it for the length of the request and
    #: never write it to a log or a URL (spec §9.5).
    player_id: str = Field(min_length=1, max_length=64)
    #: The game server / zone, for the games that ask for one. Send what the
    #: SKU's product declares; omit it otherwise. ``min_length=1`` so that an
    #: empty string is a refusal rather than a third spelling of "no server":
    #: downstream it would read as ``None`` (``server_id or "-"`` in the cache
    #: key), and a client that sent ``""`` meaning something else would never
    #: find out.
    server_id: str | None = Field(default=None, min_length=1, max_length=64)


class MerchantPlayerCheckOut(BaseModel):
    """Body of ``POST /merchant/v1/validate/player`` — an **advisory** verdict.

    Four outcomes, and the difference between them is the whole point of the
    endpoint. Switch on ``status``; never treat "not ``invalid``" as approval.

    * ``valid`` — the provider resolved the id. ``name`` carries the account
      nickname where the provider returns one (G2B does; Steam has no display
      name to give, so it stays ``null`` — an absence, not a placeholder).
    * ``invalid`` — the provider answered and the id does not exist. This is
      the one answer that says your customer mistyped something.
    * ``error`` — **we could not check.** An upstream fault, a timeout, a
      rejected credential of ours, or a circuit we opened after a run of
      failures. It says nothing at all about the id, so it must not be read as
      either approval or refusal; retry, or order without a check.
    * ``unsupported`` — this SKU's product has no player check configured, and
      will not grow one on its own. Distinct from ``error`` because that one is
      worth retrying and this one never is.

    Nothing here reports how the answer was reached, deliberately: a verdict
    served from the 300 s cache is still our best answer, and a "this was
    cached" caveat would only invite integrators to distrust a good one.
    """

    status: Literal["valid", "invalid", "error", "unsupported"]
    name: str | None = None


class MerchantTransactionOut(BaseModel):
    """One movement of the merchant's deposit.

    ``amount_usd`` is **signed**: positive credited the deposit, negative spent
    it. The column adds up to the balance ``GET /merchant/v1/me`` reports.
    """

    transaction_id: str
    #: ``merchant_deposit_credit`` (we credited your deposit),
    #: ``merchant_order_charge`` (an order spent it),
    #: ``merchant_order_refund`` (M3b: we returned a failed order's charge),
    #: and more later. Treat an unknown kind as "some movement" and trust
    #: ``amount_usd``.
    kind: str
    amount_usd: UsdAmount
    #: Set on every row that names an order, and that is **not** the same
    #: as "not a credit": since M3b Task 2 a support settlement booked
    #: against a failed order is a ``merchant_deposit_credit`` carrying one.
    #: ``null`` means the movement belongs to no order — an ordinary
    #: prepayment.
    order_id: str | None
    #: The same order's ``merchant_order_id`` — your own reference, so a
    #: statement line reconciles against your books without a second lookup.
    merchant_order_id: str | None
    created_at: datetime


class MerchantTransactionsOut(BaseModel):
    """Body of ``GET /merchant/v1/transactions`` — one page, newest first."""

    items: list[MerchantTransactionOut]
    #: Pass back as ``?cursor=`` for the next (older) page. ``null`` means
    #: this page is the last one — never call again on a null.
    next_cursor: str | None


__all__ = [
    "MerchantBrandOut",
    "MerchantCatalogOut",
    "MerchantDeliveryOut",
    "MerchantOrderCreateIn",
    "MerchantOrderEventOut",
    "MerchantOrderOut",
    "MerchantOrderStatusOut",
    "MerchantPlayerCheckIn",
    "MerchantPlayerCheckOut",
    "MerchantProductOut",
    "MerchantProfileOut",
    "MerchantSkuOut",
    "MerchantTransactionOut",
    "MerchantTransactionsOut",
    "MerchantValidationProblem",
    "SkuId",
    "UsdAmount",
    "UsdBalance",
    "UsdPrice",
]
