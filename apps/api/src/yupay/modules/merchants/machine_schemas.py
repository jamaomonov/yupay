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

from yupay.modules.catalog.unit_sku import UNIT_QTY_WIRE_MAX

_CENT = Decimal("0.01")
_MICRO = Decimal("0.000001")


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


def _micros_up(value: Decimal) -> Decimal:
    """Quantize a **per-unit** USD price to six decimals, rounding up.

    A third shape, and the note above explains why it has to be its own rather
    than a widened ``UsdPrice``: a machine contract cannot hand a client two
    shapes for one quantity, so a field is either always cents or always
    micros. This one is always micros, and it appears only on a unit SKU,
    where the cent is too coarse to price with — one Telegram Star costs about
    a cent and a half, so rounding its price to the cent is a 29% markup.

    Up, like ``_cents_up`` and for the same reason: never advertise less than
    we charge. The value published here is the exact multiplicand of the order
    total, so a merchant can reproduce their charge before sending it.
    """
    return value.quantize(_MICRO, rounding=ROUND_CEILING)


#: A USD price for one unit of a unit-priced SKU, on the wire.
UsdUnitPrice = Annotated[Decimal, AfterValidator(_micros_up)]


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

    type: str = Field(description="A URL identifying this error class.")
    title: str = Field(description="A short, human-readable summary.")
    status: int = Field(description="The HTTP status code, repeated in the body.")
    detail: str = Field(description="What went wrong, in one sentence.")
    code: str = Field(
        description=(
            "Always `invalid_request` here. Switch on this rather than on the "
            "status: every error on this API carries one, so no case is special."
        )
    )
    errors: list[dict[str, Any]] = Field(
        description=(
            "Per-field failures — `{type, loc, msg, input, ctx}` — for diagnostics. "
            "Read them when you are debugging; do not switch on them. They are the "
            "validation framework's shape and are not part of this contract."
        )
    )


class MerchantProfileOut(BaseModel):
    """Body of ``GET /merchant/v1/me`` — who is calling, and what they can spend.

    ``balance_usd`` is the deposit ledger's signed posting sum
    (``service.deposit_balance``), read live on every call — there is no
    balance column to drift from it.
    """

    merchant_id: str = Field(description="Your account id. Quote it to support.")
    title: str = Field(description="Your company name, as it appears on your invoices.")
    status: str = Field(
        description=(
            "`active`, or `frozen` while the account is suspended. A frozen account "
            "can still read, and every write answers `403 merchant_frozen`."
        )
    )
    balance_usd: UsdBalance = Field(
        description=(
            "What you can spend right now, in USD. Summed from the deposit ledger on "
            "every call — there is no stored balance that could drift from it."
        )
    )


class MerchantSkuOut(BaseModel):
    """One purchasable line of the wholesale price list.

    ``sku_id`` is what ``POST /merchant/v1/orders`` takes. Every price here is
    THIS merchant's, not the retail one. ``updated_at`` is the SKU row's own
    stamp, so a merchant polling the price list can tell what moved (spec §8.4
    — there are no price webhooks).

    **Two shapes, and ``kind`` says which.** A fixed SKU is a denomination:
    one ``price_usd``, order one of it. A unit SKU is a currency sold by the
    unit: a six-decimal ``unit_price_usd`` and a ``quantity`` on the order.
    Exactly one of the two price fields is ever populated, because a machine
    contract cannot hand a client two shapes for one quantity — and "price" on
    a unit SKU is not one quantity but two, the per-unit rate and the total.
    """

    sku_id: str = Field(description="What `POST /merchant/v1/orders` takes. Stable forever.")
    sku_code: str = Field(
        description="Our internal code for the line. Useful in a support conversation."
    )
    name: str = Field(
        description=(
            'The denomination, as a person would read it ("60 UC"). Falls back to '
            "`sku_code` for lines that carry none. The same string in every locale — "
            "denominations are not translated."
        )
    )
    kind: Literal["fixed", "unit", "amount"] = Field(
        description=(
            "Which shape this line is, and therefore what to send beside `sku_id`:\n\n"
            "- `fixed` — a denomination you buy one of. Nothing extra.\n"
            "- `unit` — a currency counted in units (Telegram Stars). Send `quantity`.\n"
            "- `amount` — a balance loaded in dollars (a Steam wallet). Send `amount_usd`."
        )
    )
    price_usd: UsdPrice | None = Field(
        default=None,
        description=(
            "`kind=fixed` only: the order total, and what to send as `expected_price`. "
            "`null` on the other two shapes, which have no price until a quantity is "
            "chosen."
        ),
    )
    unit_price_usd: UsdUnitPrice | None = Field(
        default=None,
        description=(
            "`kind=unit` and `kind=amount`: the price of **one** unit at six decimals — "
            "one Star, or one dollar of wallet balance. Your total is "
            "`ceil_to_cent(unit_price_usd × quantity_or_amount)`, computed from this "
            "exact value, so you can reproduce your charge before you send it. "
            "`null` on a fixed line."
        ),
    )
    unit: str | None = Field(
        default=None, description='`kind=unit` only: what one unit is, for your UI ("stars").'
    )
    min_qty: int | None = Field(
        default=None, description="`kind=unit` only: the smallest `quantity` we accept, inclusive."
    )
    max_qty: int | None = Field(
        default=None, description="`kind=unit` only: the largest `quantity` we accept, inclusive."
    )
    retail_price_usd: UsdPrice | None = Field(
        default=None,
        description=(
            "What the same thing costs on yupay.uz — the reference your wholesale price "
            "is a discount against, so you do not have to match SKUs by hand. "
            "`null` on a `kind=amount` line, where retail is charged as a live FX rate "
            "times a margin and there is no single figure to quote."
        ),
    )
    min_amount_usd: UsdPrice | None = Field(
        default=None,
        description=(
            "`kind=amount` only: the smallest `amount_usd` we accept, inclusive, in "
            "dollars of face value. `unit_price_usd` is then the price of **one dollar** "
            "of that balance."
        ),
    )
    max_amount_usd: UsdPrice | None = Field(
        default=None,
        description="`kind=amount` only: the largest `amount_usd` we accept, inclusive.",
    )
    updated_at: datetime = Field(
        description=(
            "When this line last changed. Poll the catalog and compare it to tell what "
            "moved — there are no price webhooks."
        )
    )


class MerchantFieldOut(BaseModel):
    """One input a product's ``fulfillment_data`` expects.

    The machine API has always told an integrator that ``fulfillment_data`` is
    required and never *what it takes* — that lived in prose, which means every
    new product is a documentation round trip before a reseller can sell it.
    This is the same schema the storefront renders its checkout form from,
    trimmed to what a caller needs: the key to send, whether it is optional,
    and the pattern we will validate against before anything is charged.

    ``label`` and ``placeholder`` are locale maps because the cabinet renders
    them to a person; a machine caller can ignore both and read ``key``.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="The key to put in `fulfillment_data`.")
    type: str = Field(description='What kind of value it is ("text", "number").')
    required: bool = Field(description="Whether the order is refused without it.")
    label: dict[str, str] = Field(
        default_factory=dict,
        description="Locale → label, for your own UI. A machine caller can ignore it.",
    )
    placeholder: dict[str, str] = Field(
        default_factory=dict, description="Locale → placeholder text, for your own UI."
    )
    pattern: str | None = Field(
        default=None,
        description=(
            "The regex we validate against before anything is charged. Check it in your "
            "own form and save the round trip."
        ),
    )


class MerchantProductOut(BaseModel):
    """One product of a brand, with its purchasable SKUs.

    Only products with at least one purchasable SKU appear — there are no
    empty shells to iterate past. ``name`` is the catalog's default locale
    (``catalog.service.DEFAULT_LOCALE``, ``ru``); ``slug`` is the stable
    machine-readable half and never changes with a translation edit.
    """

    product_id: str = Field(description="Our id for the product.")
    slug: str = Field(
        description="The stable machine-readable name. Never changes with a translation edit."
    )
    name: str = Field(description="The product name, in the catalog's default locale.")
    required_fields: list[MerchantFieldOut] = Field(
        default_factory=list,
        description="What every SKU under this product needs in `fulfillment_data`.",
    )
    skus: list[MerchantSkuOut] = Field(description="The purchasable lines, cheapest first.")


class MerchantBrandOut(BaseModel):
    """One brand of the wholesale catalog, with its products.

    ``name`` is the catalog's default locale, like the product's; a brand
    whose products all price out is absent entirely rather than empty.
    """

    brand_id: str = Field(description="Our id for the brand.")
    slug: str = Field(description="The stable machine-readable name.")
    name: str = Field(description="The brand name, in the catalog's default locale.")
    category_slug: str | None = Field(
        default=None,
        description=(
            "Which storefront section this brand sits in — the same split a person sees "
            "on yupay.uz. `null` if it has none; the brand is still listed, because the "
            "price list's job is prices."
        ),
    )
    category_name: str | None = Field(
        default=None, description="That section's name, in the catalog's default locale."
    )
    logo_url: str | None = Field(
        default=None,
        description=(
            "Brand artwork, an absolute URL — the same file the storefront renders. "
            "`null` where none is uploaded, so you can draw a placeholder instead of a "
            "broken image."
        ),
    )
    hero_image_url: str | None = Field(
        default=None, description="Wider brand artwork, an absolute URL, or `null`."
    )
    products: list[MerchantProductOut] = Field(
        description="Products with at least one purchasable SKU. Never an empty shell."
    )


class MerchantCatalogOut(BaseModel):
    """Body of ``GET /merchant/v1/catalog``: the whole B2B price list.

    An object rather than a bare array so v1 clients keep parsing when a
    future field (a cursor, a generated-at stamp) is added beside ``brands``.
    """

    brands: list[MerchantBrandOut] = Field(
        description="Every brand you can buy from, priced for your account."
    )


class MerchantOrderCreateIn(BaseModel):
    """Body of ``POST /merchant/v1/orders`` (spec §9.1).

    One SKU per order, deliberately: a reseller's own basket does not have to
    be ours, and a single line keeps "the order failed" from meaning "part of
    the order failed". An ``items`` array can still be *added* later without a
    ``/merchant/v2`` — a new optional request field is additive; removing one
    is not, which is the escape hatch ``quantity`` below was added through.

    ``extra="forbid"`` on purpose. On a response, ignoring an unknown field is
    right; on a *request* it is how a typo'd ``fulfilment_data`` silently
    becomes an order with no player id, delivered to nobody.
    """

    model_config = ConfigDict(extra="forbid")

    merchant_order_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[\x21-\x7e]+$",
        description=(
            "**Your** id for this order, and the idempotency key — send the same one "
            "again and you get the same order back, never a second charge. Printable "
            "ASCII with no spaces, so it survives being a path segment in "
            "`GET /merchant/v1/orders/{merchant_order_id}` and the signing string."
        ),
    )
    sku_id: SkuId = Field(
        description="From `GET /merchant/v1/catalog`. A UUID; any spelling of it is accepted."
    )
    quantity: int | None = Field(
        default=None,
        ge=1,
        le=UNIT_QTY_WIRE_MAX,
        description=(
            "How many units, on a `kind=unit` SKU. **Required** there and **refused** "
            "on the other shapes, both as a 422 — neither direction has a silent "
            "default, because a missing quantity would sell one Star and an ignored one "
            "would charge for a denomination you thought was ten. Bounded by that SKU's "
            "`min_qty` and `max_qty`."
        ),
    )
    amount_usd: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
        description=(
            "How many dollars of face value, on a `kind=amount` SKU. Required there and "
            "refused elsewhere, on the same no-silent-default rule as `quantity`. "
            "This is the **face value you are loading**, not what you pay: $100 of "
            "Steam wallet costs $104 at a 4% markup. Bounded by that SKU's "
            "`min_amount_usd` and `max_amount_usd`."
        ),
    )
    expected_price: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=2,
        description=(
            "The **order total** you last computed from `/catalog` — a fixed SKU's "
            "`price_usd`, or `ceil_to_cent(unit_price_usd × quantity_or_amount_usd)`.\n\n"
            "A tolerance, **not a bid**: within ±2% of ours the order proceeds and is "
            "charged at *our* current price; outside it you get `422 price_changed` "
            "carrying that price, and you decide whether to re-send."
        ),
    )
    fulfillment_data: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Whatever the SKU's product requires — a player id, a login. The keys and "
            "their patterns are published on each product as `required_fields`. An "
            "undeclared key is **rejected**, not dropped, so a SKU that requires "
            "nothing accepts only `{}`."
        ),
    )


class MerchantOrderOut(BaseModel):
    """Body of ``POST /merchant/v1/orders``.

    ``status`` is the order's live status, not a fixed ``"paid"``: a merchant
    order is born paid and fulfilment starts in the same transaction, so what
    comes back is where that left it. Poll
    ``GET /merchant/v1/orders/{merchant_order_id}`` for the rest.
    """

    merchant_order_id: str = Field(description="The id you sent. Key your records on it.")
    order_id: str = Field(
        description="Our id for the order. Quote it to support; key nothing on it."
    )
    status: str = Field(description="Where the order is right now. See the order read.")
    sku_id: str = Field(description="The SKU you bought.")
    price_usd: UsdPrice = Field(
        description=(
            "What this order charged — **our** price at the moment you ordered, within "
            "±2% of the `expected_price` you sent or it would have been refused. Fixed "
            "from here on: whatever fulfilment ends up costing us is our problem."
        )
    )
    balance_usd: UsdBalance = Field(description="Your deposit after this order.")
    created_at: datetime = Field(description="When the order was placed, ISO 8601 UTC.")


class MerchantOrderEventOut(BaseModel):
    """One entry of an order's timeline.

    ``event`` only — no payload. An ``order_events`` payload carries internal
    values (``order.paid``'s is a fingerprint of the reseller's own request;
    ``order.failed``'s is an operator's free-text note when support closed the
    order by hand, and an internal label when the automatic refund closed it —
    M3c Task 6), and none of them is worth a field on a third-party contract.
    """

    event: str = Field(
        description=(
            "One of the published `order.*` kinds. Internal audit entries are omitted "
            "entirely, and a new kind stays omitted until it is documented."
        )
    )
    at: datetime = Field(description="When it happened, ISO 8601 UTC.")


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

    artifact_kind: str = Field(
        description=(
            "What was delivered: `voucher_code` or `topup_receipt`. It decides the shape "
            "of `artifact`."
        )
    )
    artifact: dict[str, Any] = Field(
        description=(
            "The delivered thing. For `voucher_code` it carries `code` (or `codes`). "
            "Internal fields — our supplier, their order id, our warehouse row — are "
            "never in here."
        )
    )
    delivered_at: datetime = Field(description="When it was handed over, ISO 8601 UTC.")


class MerchantOrderStatusOut(BaseModel):
    """Body of ``GET /merchant/v1/orders/{merchant_order_id}``.

    The reseller's whole view of one order: where it is, what it cost, what it
    delivered, and whether anything came back. **This is the only place the
    delivered voucher code is handed over** — the ``order.status_changed``
    webhook (M3a, ADR-0070) does not carry it, because a webhook body lands in
    the merchant's logs and in ours, and a voucher code is a bearer instrument.
    """

    merchant_order_id: str = Field(description="The id you placed the order with.")
    order_id: str = Field(description="Our id for the order. Quote it to support.")
    status: str = Field(
        description=(
            "`paid` → `fulfilling` → `delivered`, or `failed`.\n\n"
            "`failed` arrives two ways: support closing an undeliverable order, and a "
            "delivery failure whose **whole** charge is already back on your deposit. "
            "Read `failure_reason` to tell them apart. New values may be added — treat "
            "one you do not know as still in flight."
        )
    )
    sku_id: str = Field(description="The SKU this order was placed against.")
    price_usd: UsdPrice = Field(description="What this order charged. Final.")
    refunded_usd: UsdAmount = Field(
        description=(
            'How much of `price_usd` is back on your deposit. `"0.00"` until something '
            "comes back. Read from the ledger, so both an automatic refund and a "
            "settlement booked by hand land here. Never more than `price_usd`."
        )
    )
    created_at: datetime = Field(description="When you placed it, ISO 8601 UTC.")
    paid_at: datetime | None = Field(
        description="When the deposit was charged. A merchant order is born paid."
    )
    delivered_at: datetime | None = Field(
        description="When it was delivered, or `null` if it has not been."
    )
    failure_reason: str | None = Field(
        description=(
            "A closed vocabulary, additive only — never a supplier's or an operator's "
            "own words, because you cannot switch on prose.\n\n"
            "- `null` — nothing has gone wrong.\n"
            "- `fulfillment_delayed` — **not terminal.** Delivery has stopped; the order "
            "has not. Keep polling, do not re-order, do not refund your customer.\n"
            "- `fulfillment_failed_refunded` — delivery failed and **all** of what you "
            "paid is back.\n"
            "- `fulfillment_failed` — delivery failed; any refund is partial or pending.\n"
            "- `order_failed` — support closed the order.\n\n"
            "A loop that stops on `failure_reason != null` will stop polling an order we "
            "are about to deliver. Stop on the terminal values, not on the field."
        )
    )
    delivery: MerchantDeliveryOut | None = Field(
        description="What was delivered, once anything was. **The only place a code is given.**"
    )
    timeline: list[MerchantOrderEventOut] = Field(
        description="What happened and when, oldest first."
    )


class MerchantPlayerCheckIn(BaseModel):
    """Body of ``POST /merchant/v1/validate/player`` (spec §9.1).

    ``extra="forbid"``, for the same reason ``MerchantOrderCreateIn`` sets it:
    on a request, silently ignoring an unknown key is how a typo'd
    ``player_id`` becomes a check of nothing that answers ``unsupported`` and
    gets read as "this brand needs no verification".
    """

    model_config = ConfigDict(extra="forbid")

    brand: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
        description=(
            "The brand you are about to order from, by its slug as listed in "
            "`GET /merchant/v1/catalog`. A brand and not a SKU, because a brand is one "
            "game (ADR-0079): the id you check here is the id every SKU of the brand "
            "credits."
        ),
    )
    player_id: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "Your **end customer's** identifier — the game's player id, or the Steam "
            "login. We hold it for the length of the request and never write it to a log "
            "or a URL, which is why this endpoint is a POST."
        ),
    )
    server_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description=(
            "The game server or zone, for the games that ask for one. Send what the "
            "brand's product form declares and omit it otherwise — an empty string is "
            'refused rather than taken as a third spelling of "no server".'
        ),
    )


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
    * ``unsupported`` — no product of this brand declares a player check, and
      none will grow one on its own. Distinct from ``error`` because that one
      is worth retrying and this one never is.

    Nothing here reports how the answer was reached, deliberately: a verdict
    served from the 300 s cache is still our best answer, and a "this was
    cached" caveat would only invite integrators to distrust a good one.
    """

    status: Literal["valid", "invalid", "error", "unsupported"] = Field(
        description=(
            "Switch on this. Never read “not `invalid`” as approval.\n\n"
            "- `valid` — the provider resolved the id.\n"
            "- `invalid` — the provider answered and the id does not exist. The one "
            "answer that means your customer mistyped something.\n"
            "- `error` — **we could not check.** Says nothing about the id. Retry, or "
            "order without a check.\n"
            "- `unsupported` — no product of this brand declares a player check and none "
            "will grow one. Never worth retrying."
        )
    )
    name: str | None = Field(
        default=None,
        description=(
            "The account nickname, where the provider returns one. `null` is an absence, "
            "not a placeholder — some providers have no display name to give."
        ),
    )


class MerchantTransactionOut(BaseModel):
    """One movement of the merchant's deposit.

    ``amount_usd`` is **signed**: positive credited the deposit, negative spent
    it. The column adds up to the balance ``GET /merchant/v1/me`` reports.
    """

    transaction_id: str = Field(description="Our id for this ledger entry.")
    kind: str = Field(
        description=(
            "- `merchant_deposit_credit` — we credited your deposit.\n"
            "- `merchant_order_charge` — an order spent it.\n"
            "- `merchant_order_refund` — we returned a failed order's charge.\n\n"
            'More may be added. Treat an unknown kind as "some movement" and trust '
            "`amount_usd`."
        )
    )
    amount_usd: UsdAmount = Field(
        description=(
            "**Signed**: positive credited the deposit, negative spent it. The column "
            "adds up to the balance `GET /merchant/v1/me` reports."
        )
    )
    order_id: str | None = Field(
        description=(
            "The order this movement belongs to, if any. Present on credits too — a "
            "settlement booked against a failed order is a credit that names it. `null` "
            "means an ordinary prepayment."
        )
    )
    merchant_order_id: str | None = Field(
        description=(
            "The same order's id in **your** system, so a statement line reconciles "
            "against your books without a second lookup."
        )
    )
    created_at: datetime = Field(description="When it was posted, ISO 8601 UTC.")


class MerchantTransactionsOut(BaseModel):
    """Body of ``GET /merchant/v1/transactions`` — one page, newest first."""

    items: list[MerchantTransactionOut] = Field(description="One page, newest first.")
    next_cursor: str | None = Field(
        description=(
            "Pass back as `?cursor=` for the next, older page. `null` means this page is "
            "the last one — never call again on a null."
        )
    )


__all__ = [
    "MerchantBrandOut",
    "MerchantCatalogOut",
    "MerchantDeliveryOut",
    "MerchantFieldOut",
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
