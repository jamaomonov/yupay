"""Order service: create, get, list. Status transitions land here too."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from sqlalchemy import Text, cast, false, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from yupay.core.clock import now
from yupay.core.config import Settings
from yupay.core.errors import (
    ConflictError,
    NotFoundError,
    UpstreamUnavailableError,
    ValidationError,
)
from yupay.core.ids import new_id

# Imported as the submodule rather than through ``affiliate.api``: that
# facade gains a router in a later step, and importing a router from here
# would close a cycle back through the v1 route stack.
from yupay.modules.affiliate import discount as affiliate_discount
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.catalog.unit_sku import assert_qty_allowed, is_unit_sku
from yupay.modules.fx.models import FxSnapshot
from yupay.modules.gifts import checkout as gifts_checkout
from yupay.modules.orders.models import Order, OrderEvent, OrderItem
from yupay.modules.orders.schemas import OrderCreate, OrderItemDisplay, OrderItemIn
from yupay.modules.orders.scope import IS_SALE
from yupay.modules.orders.validation import validate_fulfillment_data
from yupay.modules.payments.models import Payment, PaymentAttempt
from yupay.modules.pricing.fx_guard import RateRejected, guarded_usd_rate
from yupay.modules.pricing.variable import display_rate, price_in_quote, validate_amount
from yupay.modules.users.models import User

# Smallest unit an acquirer will actually charge, per quote currency. UZS is
# whole so'm (tiyin coins are defunct; the catalog also prices UZS SKUs to whole
# so'm), RUB is kopecks. The full order total is rounded to this before it is
# stored so ``total_charged`` is always an exact, payable amount — Payme and Octo
# both charge in minor units and reject a sub-unit remainder.
_CURRENCY_QUANTUM: dict[str, Decimal] = {"UZS": Decimal("1")}
_DEFAULT_QUANTUM = Decimal("0.01")


def _round_to_payable(total: Decimal, currency: str) -> Decimal:
    """Round an order total to the quote currency's smallest chargeable unit.

    Args:
        total: The assembled order total, at intermediate (6 dp) precision.
        currency: The quote currency (e.g. ``"UZS"``, ``"RUB"``).

    Returns:
        ``total`` rounded half-up to the currency's payable granularity
        (whole so'm for UZS, kopecks for everything else).
    """
    quantum = _CURRENCY_QUANTUM.get(currency, _DEFAULT_QUANTUM)
    return total.quantize(quantum, rounding=ROUND_HALF_UP)


def _order_load_options() -> tuple[Any, ...]:
    """Eager-loading chain used by every read of an Order — keeps the
    OrderItemOut.display field populatable without a separate fetch."""
    return (
        selectinload(Order.items)
        .selectinload(OrderItem.sku)
        .options(
            selectinload(Sku.product).options(
                selectinload(Product.translations),
                selectinload(Product.brand).selectinload(Brand.translations),
            ),
        ),
        selectinload(Order.payments),
    )


def succeeded_provider_for(order: Order) -> str | None:
    """The provider of the order's newest succeeded payment, normalized.

    ``click_miniapp`` collapses to ``click`` (same brand). Returns ``None``
    when nothing has succeeded yet (e.g. pending_payment). Reads the
    eager-loaded ``order.payments`` collection — never triggers a query.
    """
    succeeded = [p for p in order.payments if p.status == "succeeded"]
    if not succeeded:
        return None
    latest = max(succeeded, key=lambda p: p.succeeded_at or p.created_at)
    provider = latest.provider
    return "click" if provider == "click_miniapp" else provider


def _tr_name(translations: list[Any], locale: str = "ru") -> str:
    """Pick the localised name from a translations relationship, falling back
    to the first available row when the asked locale is missing."""
    if not translations:
        return ""
    for t in translations:
        if t.locale == locale:
            return t.name or ""
    return translations[0].name or ""


def build_item_display(item: OrderItem, *, locale: str = "ru") -> OrderItemDisplay | None:
    """Build the display block for a single order item. Requires that the
    SKU → product → brand chain has been eagerly loaded."""
    sku = item.sku
    if sku is None:
        return None  # type: ignore[unreachable]
    product = sku.product
    brand = product.brand if product is not None else None
    # A unit SKU (Telegram Stars) has no fixed denomination — the line is
    # however many units the customer bought, not a catalog attribute. Read
    # it from the frozen `item.qty`, never re-derived from `amount_usd`.
    # Only format `{qty} {unit}` for a real unit purchase (`qty >= min_qty`).
    # A pre-seed free-amount line stored qty=1; after the seed the live SKU
    # looks like a unit SKU and would otherwise display as "1 Stars".
    denomination = sku.denomination
    if is_unit_sku(sku) and sku.amount_unit and sku.min_qty is not None and item.qty >= sku.min_qty:
        denomination = f"{item.qty} {sku.amount_unit}"
    elif sku.sku_code == gifts_checkout.STEAM_GIFT_SKU_CODE:
        # steam-gift is one SKU standing in for ~4200 games, so its own
        # denomination is the literal placeholder "Любая сумма". The real
        # game (and, when it differs, the edition) was snapshotted onto
        # this line at checkout by `gifts_checkout.price_gift_line`. An
        # order placed before that snapshot existed has no `app_name` —
        # `steam_gift_label` returns `None` for it, and the placeholder set
        # above stands, same as it always has.
        gift_label = gifts_checkout.steam_gift_label(item.fulfillment_data)
        if gift_label is not None:
            denomination = gift_label
    return OrderItemDisplay(
        brand_slug=brand.slug if brand is not None else "",
        brand_name=_tr_name(brand.translations, locale) if brand is not None else "",
        product_slug=product.slug if product is not None else "",
        product_name=_tr_name(product.translations, locale) if product is not None else "",
        product_kind=product.kind if product is not None else "voucher",
        sku_code=sku.sku_code,
        denomination=denomination,
        region=sku.region,
        image_url=sku.image_url or (product.image_url if product is not None else None),
        variable_amount=sku.variable_amount,
    )


# Long enough to walk through a real acquirer hop (Click / Payme / YooKassa
# typically need 1–3 min including 3DS), short enough that an abandoned cart
# doesn't squat the inventory reservation. 10 minutes matches the median
# checkout-to-confirm time on UZ acquirers we've measured.
ORDER_EXPIRY_SECONDS = 10 * 60


#: Surfaces a **client may declare for itself** via the ``X-Yupay-Surface``
#: header; anything we do not recognise (an old client, a script, a spoof)
#: records as ``unknown`` rather than being trusted verbatim, so the column
#: stays a closed set the admin can filter on.
#:
#: The B2B values below are deliberately **not** in here. They are what makes
#: the widened vocabulary safe: a storefront request that asked for
#: ``merchant_api`` would otherwise dress a retail sale up as a reseller's, on
#: the one column an operator reads to tell them apart.
ORDER_SOURCES: frozenset[str] = frozenset({"web", "miniapp", "bot"})

#: Set server-side by ``merchants.orders.place``, on a path that has already
#: authenticated which merchant is calling. Unlike a retail source this is not
#: a claim the client made about itself — which makes ``source`` stronger on
#: these rows, though still not an authorisation input.
SOURCE_MERCHANT_API: Final[str] = "merchant_api"

#: Reserved for **M4's reseller cabinet** (spec ``2026-09-06-merchant-b2b-design``
#: §milestones: "cabinet app: landing, registration + confirmation, all
#: sections"). Allowed by ``ck_orders_source_known`` since migration 0073 so
#: the cabinet needs no migration of its own for one string — and unreachable
#: until then: nothing writes it, and it is not in ``ORDER_SOURCES``, so no
#: request can declare it. A row carrying it before M4 ships means something
#: wrote it that should not have.
SOURCE_MERCHANT_PANEL: Final[str] = "merchant_panel"


def normalise_source(raw: str | None) -> str:
    """The declared surface, or ``unknown``. Never raises — an unreadable
    header must not be able to refuse a sale."""
    value = (raw or "").strip().lower()
    return value if value in ORDER_SOURCES else "unknown"


@dataclass(frozen=True)
class Actor:
    """Who is placing or reading an order. Exactly one arm is set.

    Three arms, mirroring the ``ck_orders_actor_exclusive`` CHECK the database
    has enforced since migration 0066: a logged-in user (``user_id``), a guest
    identified by their email (``email``), or a B2B reseller ordering through
    ``/merchant/v1`` (``merchant_id``).

    ``merchant_id`` is defaulted rather than required so every retail call site
    keeps constructing an actor with the same two keyword arguments it always
    did — the widening is additive, and a two-argument ``Actor`` still means
    exactly what it meant before.
    """

    user_id: str | None
    email: str | None
    merchant_id: str | None = None

    def __post_init__(self) -> None:
        arms = (self.user_id, self.email, self.merchant_id)
        if sum(arm is not None for arm in arms) != 1:
            raise ValidationError("actor must be exactly one of user_id / email / merchant_id")


def _record_event(
    db: AsyncSession,
    *,
    order_id: str,
    kind: str,
    actor: Actor,
    payload: dict[str, object] | None = None,
) -> None:
    if actor.user_id:
        actor_label = f"user:{actor.user_id}"
    elif actor.merchant_id:
        # No hashing here, unlike the guest arm below: a merchant id is an
        # internal account identifier, not the reseller's own PII, and ops needs
        # to read it straight off the audit feed. Fits the varchar(64) actor
        # column with room to spare ("merchant:" + 36-char UUID = 45 chars).
        actor_label = f"merchant:{actor.merchant_id}"
    else:
        # Store a (truncated) hash of the guest's email — not the raw address — in
        # the audit actor, keeping the plaintext email out of the admin audit feed
        # while still allowing per-guest correlation. Truncated to fit the
        # varchar(64) actor column ("guest:" + 40 hex = 46 chars); a per-email
        # deterministic pseudonym, non-reversible.
        from yupay.core.config import get_settings
        from yupay.modules.auth.security import email_hash

        _eh = email_hash(actor.email or "", get_settings().auth_email_pepper)
        actor_label = f"guest:{_eh[:40]}"
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order_id,
            kind=kind,
            payload=payload or {},
            actor=actor_label,
        )
    )


async def _fetch_skus_with_product(db: AsyncSession, sku_ids: list[str]) -> dict[str, Sku]:
    """Load all referenced SKUs along with their product + brand (for
    required_fields and the active-chain check) and per-currency price
    overrides (so checkout honours the same native price the catalogue
    showed the customer)."""
    if not sku_ids:
        return {}
    stmt = (
        select(Sku)
        .options(
            selectinload(Sku.product).selectinload(Product.brand),
            # The product's other SKUs, because a free-amount line is priced
            # from whichever package it falls in — see `tier_unit_price`. One
            # extra query, not one per line.
            selectinload(Sku.product).selectinload(Product.skus),
            selectinload(Sku.price_overrides),
        )
        .where(Sku.id.in_(sku_ids))
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {s.id: s for s in rows}


def sku_is_buyable(sku: Sku) -> bool:
    """A SKU is buyable only when it and its whole product → brand chain are
    active AND the brand is not in maintenance. ``maintenance`` is the softer
    "temporarily unavailable" state (the brand still lists, unlike
    ``active=False``) that the model documents as blocking purchases — so it
    gates checkout here but not catalog visibility. Requires ``sku.product``
    and ``sku.product.brand`` eager-loaded."""
    product = sku.product
    brand = product.brand if product is not None else None
    return bool(
        sku.active
        # Supplier stock, for gift cards and vouchers: real codes in someone
        # else's warehouse, and G2B reports plenty of lines at zero. Checked
        # here rather than only in the storefront because the count moves
        # between the page render and the pay button, and taking money for a
        # code that no longer exists costs a manual refund.
        and sku.in_stock
        and product is not None
        and product.active
        and brand
        and brand.active
        and not brand.maintenance
    )


async def _existing_idempotent_order(
    db: AsyncSession, *, actor: Actor, idempotency_key: str
) -> Order | None:
    """Replay the purchase this key already made, if any.

    Deposits share this table and this key's unique index, so a key already
    spent on one must not be replayed as a purchase: the buyer would be handed
    a wallet top-up — no items, nothing bought — as though it were the order
    they asked for. ``wallet.funding.create_topup`` refuses the mirror case;
    this is the other half of that check.
    """
    stmt = (
        select(Order)
        .options(*_order_load_options(), selectinload(Order.events))
        .where(Order.idempotency_key == idempotency_key)
    )
    if actor.user_id is not None:
        stmt = stmt.where(Order.user_id == actor.user_id)
    elif actor.merchant_id is not None:
        # Per-merchant scope, matching the per-user and per-guest scopes: two
        # resellers picking the same ``merchant_order_id`` is expected traffic
        # (they cannot see each other's keys), not a replay of one order.
        stmt = stmt.where(Order.merchant_id == actor.merchant_id)
    else:
        stmt = stmt.where(Order.guest_email == actor.email)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None and existing.purpose != "catalog":
        raise ConflictError(
            "Idempotency-Key was already used for a different request",
            extra={"purpose": existing.purpose},
        )
    return existing


def _tier_priced_amount(amount_usd: Decimal, sku: Sku) -> Decimal | None:
    """Re-price a snapped amount from the packages, or ``None`` to leave it be.

    ``None`` covers everything that is not sold by unit — the Steam wallet, and
    any unit SKU whose product has no packages to price from — so those keep
    billing the amount the customer named, exactly as before.

    The returned value is a **face value**, which is what ``unit_price_usd``
    has always held: the charge is later computed as face × rate × multiplier,
    and revenue as face × multiplier. So the package price is divided by the
    multiplier here and multiplied back downstream, leaving the customer
    charged exactly the package price. Doing it this way rather than requiring
    ``rate_multiplier = 1`` on these SKUs means a mis-set multiplier cannot
    silently charge the margin twice.
    """
    per_usd = sku.units_per_usd
    if per_usd is None or per_usd <= 0 or sku.product is None:
        return None
    units = int((amount_usd * per_usd).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if units <= 0:
        return None
    total = tier_price_usd(units, (s for s in sku.product.skus if s.id != sku.id))
    if total is None:
        return None
    multiplier = sku.rate_multiplier or Decimal("1")
    return (total / multiplier).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _snap_to_unit(amount_usd: Decimal, sku: Sku) -> Decimal:
    """Round a unit-priced amount to a whole unit before it prices anything.

    On a SKU bought in stars rather than dollars, the storefront divides the
    star count by ``units_per_usd`` and sends the result. Float noise on the way
    means 500 stars can arrive as the USD value of 499.9997 — and the supplier
    is sent an integer, so the customer would be charged for one amount and
    credited another. Snapping here makes the two agree by construction, and
    leaves a dollar-priced SKU (every existing one) untouched.
    """
    per_usd = sku.units_per_usd
    if not sku.variable_amount or per_usd is None or per_usd <= 0:
        return amount_usd
    units = (amount_usd * per_usd).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if units <= 0:
        # Below half a unit. Let the bounds check reject it with its own message
        # rather than silently selling zero.
        return amount_usd
    return (units / per_usd).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def tier_price_usd(units: int, siblings: Iterable[Sku]) -> Decimal | None:
    """What a free amount of ``units`` costs, priced from the packages.

    Margin differs per package — 20% on the small Telegram Stars packs, less on
    the large ones — so there is no single rate that prices "any amount". The
    amount is priced *from* the package it falls in: 50–74 stars at the 50-pack's
    per-star price, 75–99 at the 75-pack's. The two can then never disagree,
    whatever margins are set, because one is derived from the other.

    Two rules, and the second is the one that is easy to miss:

    * the band is the largest package at or below the amount;
    * **the amount never costs more than the next package up.** Without that,
      band pricing is not monotonic — with a 10% discount on the 500-pack, 499
      stars at the 100-pack's rate came to $9.23 while 500 cost $8.89, so buying
      less cost more. The cap flattens the top of each band instead, which is
      both monotonic and the answer in the customer's favour.

    Returns ``None`` below the smallest package rather than inventing a price;
    the caller's bounds check is what rejects that.
    """
    packs = sorted(
        (s for s in siblings if s.active and s.units is not None and s.units > 0),
        key=lambda s: s.units or 0,
    )
    band: Sku | None = None
    ceiling: Decimal | None = None
    for pack in packs:
        pack_units = pack.units or 0
        if pack_units <= units:
            band = pack
        elif ceiling is None:
            ceiling = pack.price_usd
    if band is None or band.units is None:
        return None
    total = Decimal(units) * (band.price_usd / Decimal(band.units))
    if ceiling is not None and total > ceiling:
        total = ceiling
    return total.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _resolve_line_unit_price(sku: Sku, line: OrderItemIn, currency: str) -> Decimal:
    """The USD amount one order line bills for.

    A variable-amount SKU (Steam wallet top-up) bills for the customer's
    chosen ``amount_usd``, validated against the SKU's own bounds; a fixed
    SKU bills for its catalog ``price_usd`` and must not receive an amount at
    all — either direction of mismatch is a 422, never a silently-ignored or
    silently-zeroed price.

    Two more illegal combinations are refused here, before pricing or
    fulfillment ever sees them:

    * ``qty != 1`` on a variable-amount line. Fulfillment creates exactly one
      ``FulfillmentTask`` per ``OrderItem`` and sends the supplier
      ``unit_price_usd`` with no ``× qty`` — so "qty=2" would charge the
      customer twice while topping up only once. Quantity is meaningless for
      a customer-chosen amount anyway: buying more means entering a bigger
      amount, not a higher qty.
    * ``currency == "USD"`` on a variable-amount line. The whole pricing
      model for these SKUs is "USD amount × guarded local-currency rate ×
      margin multiplier" — there is no margin-bearing USD price, so a USD
      sale would be face value at zero margin (or below cost, once a
      supplier fee is configured).

    Raises:
        ValidationError: ``qty`` is outside the SKU's real bounds (see
            ``assert_qty_allowed`` — the wire-level ``OrderItemIn.qty`` max is
            raised for unit SKUs and is not the real limit for anything
            else), ``amount_usd`` is missing/out of bounds for a variable
            SKU, present for a fixed one, or the line is a variable-amount
            SKU with ``qty != 1`` or ``currency == "USD"``.
    """
    assert_qty_allowed(sku, line.qty)
    if sku.variable_amount:
        if line.qty != 1:
            raise ValidationError(
                "this product is bought by amount, not quantity — set qty to 1 and "
                "adjust amount_usd instead",
                extra={"sku_id": sku.id, "qty": line.qty},
            )
        if currency == "USD":
            raise ValidationError(
                "this product cannot be purchased in USD — choose a local currency",
                extra={"sku_id": sku.id, "currency": currency},
            )
        if line.amount_usd is None:
            raise ValidationError("amount is required for this product", extra={"sku_id": sku.id})
        amount = _snap_to_unit(line.amount_usd, sku)
        validate_amount(
            amount,
            minimum=sku.min_amount_usd or Decimal("0"),
            maximum=sku.max_amount_usd or Decimal("0"),
        )
        # `amount` is still the unit count expressed in dollars, which is only
        # a way of naming the count unambiguously. What gets billed is the
        # package-derived price, so the free amount and the packages cannot
        # drift apart when their margins differ.
        priced = _tier_priced_amount(amount, sku)
        return priced if priced is not None else amount
    if line.amount_usd is not None:
        raise ValidationError("this product has a fixed price", extra={"sku_id": sku.id})
    return sku.price_usd


async def _variable_line_charge(
    db: AsyncSession,
    *,
    sku: Sku,
    unit_price_usd: Decimal,
    qty: int,
    currency: str,
    rate_cache: dict[str, Decimal],
) -> tuple[Decimal, Decimal]:
    """Amount charged, in ``currency``, for one variable-amount line.

    Never uses a ``SkuPrice`` override or the plain FX snapshot — only the
    guarded rate times the SKU's own margin multiplier. ``rate_cache``
    memoizes the guarded market rate per currency across an order's lines:
    every variable line in the same currency shares the same market rate
    (only the multiplier differs per SKU), so this avoids re-querying the
    FX trust gate once per line.

    Returns:
        ``(charge, market_rate)``. The market rate is handed back rather than
        left in ``rate_cache`` for the caller to fish out, because the caller
        has to record it on the line (ADR-0051) and an implicit read of a
        cache someone else populated is how that quietly stops happening.

    Raises:
        UpstreamUnavailableError: the FX trust gate rejects the rate.
    """
    market = rate_cache.get(currency)
    if market is None:
        try:
            market = await guarded_usd_rate(db, quote=currency)
        except RateRejected as exc:
            raise UpstreamUnavailableError(
                "Цена временно недоступна. Попробуйте позже.",
                base="USD",
                quote=currency,
                reason=exc.reason,
            ) from exc
        rate_cache[currency] = market
    rate = display_rate(market, sku.rate_multiplier or Decimal("1"))
    return price_in_quote(unit_price_usd, rate=rate) * qty, market


async def _snapshot_id_for_rate(db: AsyncSession, *, quote: str, rate: Decimal) -> str | None:
    """Recover the ``fx_snapshots`` row id backing a rate obtained through
    :func:`~yupay.modules.pricing.fx_guard.guarded_usd_rate`.

    The guard persists (or reuses) a snapshot internally but only returns the
    ``Decimal`` rate, not the row — so this looks the row back up by matching
    on the exact rate value (not just base/quote), which rules out binding
    the order to a different, unrelated snapshot that a concurrent request
    might have written for the same currency in between. Picks the most
    recent match if more than one row happens to share the rate. Returns
    ``None`` on the (practically impossible) chance no matching row is found
    — a missing audit id, never a reason to fail an already-guarded charge.
    """
    stmt = (
        select(FxSnapshot.id)
        .where(
            FxSnapshot.base == "USD",
            FxSnapshot.quote == quote,
            FxSnapshot.rate == rate,
        )
        .order_by(FxSnapshot.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _compute_total_charged(
    db: AsyncSession,
    *,
    body: OrderCreate,
    skus: dict[str, Sku],
    items: list[OrderItem],
    total_usd: Decimal,
    currency: str,
) -> tuple[Decimal, str | None]:
    """Per-currency total. Catalog already returned a native price for SKUs
    that have a ``SkuPrice`` override in the order currency — checkout must
    charge that exact figure, otherwise the user sees one number in the
    package picker and a different (FX-derived) one at submit. Falls back to
    the guarded FX rate (:func:`~yupay.modules.pricing.fx_guard.guarded_usd_rate`
    — the same trust gate :func:`_variable_line_charge` and the catalog use)
    only when no override exists for the selected currency, so a fixed-price
    line can never be charged off a wrong or stale rate the gate would
    otherwise have rejected.

    The ``currency == "USD"`` short-circuit below is only safe because
    ``_resolve_line_unit_price`` already refused any variable-amount line
    paired with ``currency == "USD"`` — by the time an order reaches this
    function, USD + variable-amount can no longer coexist, so face-value
    ``total_usd`` is never mistaken for a margin-bearing price on one of
    those lines.

    Returns:
        ``(total_charged, fx_snapshot_id)`` — ``fx_snapshot_id`` stays
        ``None`` when every line was priced from an override or USD.

    Raises:
        UpstreamUnavailableError: the FX trust gate rejects the rate needed
            for a fixed-price, non-override line — the SKU falls out of sale
            for that currency rather than charging on an untrusted rate.
    """
    if currency == "USD":
        return total_usd, None

    total_charged = Decimal("0")
    fx_snapshot_id: str | None = None
    # Shared with ``_variable_line_charge``: both branches want the exact same
    # guarded USD→currency market rate (pre-multiplier), so whichever line
    # type resolves it first spares every later line — of either type — a
    # repeat trip through the FX trust gate.
    rate_cache: dict[str, Decimal] = {}
    for line, item in zip(body.items, items, strict=True):
        sku = skus[line.sku_id]

        if sku.variable_amount:
            charge, market = await _variable_line_charge(
                db,
                sku=sku,
                unit_price_usd=item.unit_price_usd,
                qty=line.qty,
                currency=currency,
                rate_cache=rate_cache,
            )
            total_charged += charge
            # Frozen here, where the rate that priced this line is in hand
            # (ADR-0051). Without it the line's value in USD is only knowable
            # by re-reading a `Sku.rate_multiplier` an admin may since have
            # changed, which silently revalues every past order.
            item.rate_multiplier = sku.rate_multiplier
            item.fx_rate = market
            continue

        override = next(
            (o for o in sku.price_overrides if o.currency.upper() == currency),
            None,
        )
        if override is not None:
            # No rate participated: the override *is* the price in this
            # currency. Both stay NULL, which is what says so.
            total_charged += override.price * line.qty
            continue

        rate = rate_cache.get(currency)
        if rate is None:
            try:
                rate = await guarded_usd_rate(db, quote=currency)
            except RateRejected as exc:
                raise UpstreamUnavailableError(
                    f"Не удалось получить курс USD→{currency}. Попробуйте позже или "
                    "оплатите в USD.",
                    base="USD",
                    quote=currency,
                    reason=exc.reason,
                ) from exc
            rate_cache[currency] = rate
        if fx_snapshot_id is None:
            fx_snapshot_id = await _snapshot_id_for_rate(db, quote=currency, rate=rate)
        # A fixed line carries no multiplier — its USD value is already
        # `unit_price_usd` — but the rate it converted at is still worth
        # keeping, for "what did we quote them" (ADR-0051).
        item.fx_rate = rate
        total_charged += (sku.price_usd * line.qty * rate).quantize(Decimal("1.000000"))

    # Line prices carry 6 dp for intermediate precision (see
    # ``pricing.variable.price_in_quote``); the assembled total is rounded to
    # the currency's smallest chargeable unit here so ``total_charged`` is an
    # exact, payable amount — a sub-unit remainder is unpayable via Payme/Octo.
    return _round_to_payable(total_charged, currency), fx_snapshot_id


@dataclass(frozen=True)
class CartQuote:
    """What a cart would cost, without creating anything."""

    total_usd: Decimal
    total_charged: Decimal
    currency: str


async def quote_cart(db: AsyncSession, body: OrderCreate) -> CartQuote:
    """Price a cart without persisting an order.

    Shares ``_resolve_line_unit_price`` and ``_compute_total_charged`` with
    :func:`create_order`, so a quote and the order that follows it cannot
    disagree about price. A second implementation of "what does this cost" is
    the one thing this function exists to avoid.

    Fulfillment data is deliberately not validated: a quote is about money, and
    the buyer may not have typed their player ID yet when they try a promo code.

    Args:
        db: Session.
        body: The same payload ``create_order`` takes. Only ``items`` and
            ``currency`` are read.

    Returns:
        The cart's totals, before any affiliate discount.

    Raises:
        ValidationError: If any SKU is unknown, inactive, or hidden behind an
            inactive product or brand — the same rule checkout applies.
    """
    sku_ids = [item.sku_id for item in body.items]
    skus = await _fetch_skus_with_product(db, sku_ids)
    missing = [sid for sid in sku_ids if sid not in skus or not sku_is_buyable(skus[sid])]
    if missing:
        raise ValidationError("unknown or inactive SKU", extra={"sku_ids": missing})

    currency = body.currency.upper()
    items: list[OrderItem] = []
    total_usd = Decimal("0")
    for line in body.items:
        sku = skus[line.sku_id]
        unit_price_usd = _resolve_line_unit_price(sku, line, currency)
        items.append(
            OrderItem(
                id=new_id(),
                order_id=new_id(),
                sku_id=sku.id,
                qty=line.qty,
                unit_price_usd=unit_price_usd,
                cost_usdt=None if sku.variable_amount else sku.cost_usdt,
                fulfillment_data={},
            )
        )
        total_usd += unit_price_usd * line.qty

    total_charged, _snapshot = await _compute_total_charged(
        db,
        body=body,
        skus=skus,
        items=items,
        total_usd=total_usd,
        currency=currency,
    )
    # The OrderItems above are never added to the session — they exist only to
    # give the shared pricing helpers the shape they expect, and are discarded
    # when this function returns.
    return CartQuote(total_usd=total_usd, total_charged=total_charged, currency=currency)


def _check_merchant_only_arguments(
    body: OrderCreate,
    *,
    actor: Actor,
    unit_price_usd_override: Sequence[Decimal] | None,
    merchant_expected_price_usd: Sequence[Decimal] | None,
) -> None:
    """Refuse the combinations that only make sense on the B2B channel.

    All three are guards on the same seam, which is why they live together:
    the price override exists so a wholesale price can reach an order, the
    quote record rides beside it, and the affiliate refusal exists so a
    *retail* discount cannot reach that same order from the other side.

    Args:
        body: The parsed request.
        actor: Who is buying.
        unit_price_usd_override: The per-line override, if the caller passed
            one.
        merchant_expected_price_usd: The per-line merchant quote, if the
            caller passed one.

    Raises:
        ValidationError: The override or the quote came from a non-merchant
            actor or does not line up with ``body.items``, or a merchant order
            names an affiliate code.
    """
    if unit_price_usd_override is not None:
        if actor.merchant_id is None:
            raise ValidationError("a unit-price override is only accepted from a merchant actor")
        if len(unit_price_usd_override) != len(body.items):
            raise ValidationError(
                "a unit-price override must carry one unit price per line",
                lines=len(body.items),
                prices=len(unit_price_usd_override),
            )
    if merchant_expected_price_usd is not None:
        # Guarded exactly like the override above, and for a weaker but real
        # reason: the column is documented as "what a merchant quoted", so a
        # retail line carrying a number would make every reader of it wrong
        # about which orders have one.
        if actor.merchant_id is None:
            raise ValidationError("a merchant quote is only accepted from a merchant actor")
        if len(merchant_expected_price_usd) != len(body.items):
            raise ValidationError(
                "a merchant quote must carry one price per line",
                lines=len(body.items),
                prices=len(merchant_expected_price_usd),
            )
    if body.affiliate_code and actor.merchant_id is not None:
        # ``resolve_code`` is called with ``user_id=actor.user_id``, which is
        # NULL on the merchant arm — so the code would resolve like a *guest's*
        # and take a retail discount off an already-wholesale price. Refused
        # rather than stripped: a merchant body cannot carry the field at all
        # (``machine_schemas.MerchantOrderCreateIn`` forbids extras), so
        # anything reaching here is our own bug and should be loud.
        raise ValidationError("affiliate codes do not apply to merchant orders")


async def create_order(
    db: AsyncSession,
    body: OrderCreate,
    *,
    actor: Actor,
    idempotency_key: str,
    settings: Settings | None = None,  # noqa: ARG001 -- reserved for future per-request config
    ip_hash: str | None = None,
    ua_hash: str | None = None,
    source: str = "unknown",
    unit_price_usd_override: Sequence[Decimal] | None = None,
    merchant_expected_price_usd: Sequence[Decimal] | None = None,
) -> Order:
    """Validate, snapshot price + FX, persist the order. Idempotent per actor.

    Args:
        db: Session. The caller owns the transaction.
        body: The parsed request.
        actor: Who is buying — a user, a guest, or a merchant.
        idempotency_key: The replay handle, scoped per actor arm by a partial
            UNIQUE (``uq_orders_idem_user`` / ``_guest`` / ``_merchant``). For
            a merchant this is their own ``merchant_order_id`` (spec §9.3).
        settings: Reserved.
        ip_hash: Hashed client address, for the risk trail.
        ua_hash: Hashed user agent, for the risk trail.
        source: Which surface placed the order — the client's declared
            ``X-Yupay-Surface`` for retail (already normalised by
            :func:`normalise_source`), or ``SOURCE_MERCHANT_API`` set
            server-side by ``merchants.orders.place``.
        unit_price_usd_override: **Merchant-only.** One USD unit price per
            line of ``body.items``, in order, replacing the catalog price this
            function would otherwise resolve. It exists because a B2B order is
            priced by ``merchants.pricing`` — cost plus a wholesale markup —
            and forking this function to say so would give the storefront and
            the machine API two different definitions of "an order". Passing
            it with a non-merchant actor is a ``ValidationError``, not a
            silently-ignored argument: a retail price arriving from the client
            is the one thing this seam must never become.
        merchant_expected_price_usd: **Merchant-only.** One quoted USD price
            per line — what the reseller said they expected to pay — recorded
            on the line and read by nothing (spec item 3b, ADR-0071). It is
            not an input to any price: ``merchants.quote.price_for`` has
            already decided the charge before this function is called, and a
            different number here moves no money. Kept as its own argument
            rather than folded into ``unit_price_usd_override`` because the
            two answer different questions — one is what we charge, the other
            is what they said — and one sequence of pairs would make an error
            in either look like an error in both.

    Returns:
        The persisted order (with items + events loaded).

    Raises:
        ValidationError: An unknown or unbuyable SKU, invalid
            ``fulfillment_data``, a price override or a merchant quote from a
            non-merchant actor or of the wrong length, or an affiliate code on
            a merchant order.
        ConflictError: The idempotency key belongs to a different kind of
            request, or a concurrent create won the race and left nothing to
            replay.
    """
    _check_merchant_only_arguments(
        body,
        actor=actor,
        unit_price_usd_override=unit_price_usd_override,
        merchant_expected_price_usd=merchant_expected_price_usd,
    )
    existing = await _existing_idempotent_order(db, actor=actor, idempotency_key=idempotency_key)
    if existing is not None:
        return existing

    # 1) Load SKUs once. A line is buyable only if the whole SKU → product →
    # brand chain is active — deactivating a brand doesn't cascade to its
    # SKUs, so checking only ``sku.active`` would let a hidden brand's product
    # still be paid for.
    sku_ids = [item.sku_id for item in body.items]
    skus = await _fetch_skus_with_product(db, sku_ids)
    missing = [sid for sid in sku_ids if sid not in skus or not sku_is_buyable(skus[sid])]
    if missing:
        raise ValidationError("unknown or inactive SKU", extra={"sku_ids": missing})

    # 2) Build order items with frozen price + validated fulfillment_data.
    # Resolved once, up front, so the variable-amount×USD guard in
    # _resolve_line_unit_price sees the real order currency for every line.
    currency = body.currency.upper()
    order_id = new_id()
    items: list[OrderItem] = []
    total_usd = Decimal("0")
    for index, line in enumerate(body.items):
        sku = skus[line.sku_id]
        product: Product = sku.product
        cleaned = validate_fulfillment_data(product=product, data=line.fulfillment_data)
        # Still resolved for a merchant line, and deliberately: this is where
        # the qty bounds and the fixed-vs-variable rules are enforced, and a
        # B2B order has to obey them too. Only the resulting number is
        # replaced, at the end of the branch, so nothing can price around it.
        unit_price_usd = _resolve_line_unit_price(sku, line, currency)
        if gifts_checkout.is_gift_sku(sku):
            # Outbound HTTP call on the request path — the spec §4.3-mandated
            # server re-price, not client-trusted. Bounded by the 15-min
            # gifts:detail cache (gifts/service.py::get_app) and the G-Engine
            # client's own request timeout, so this is the documented §10
            # exception to "no synchronous external HTTP in request handlers".
            unit_price_usd, cleaned = await gifts_checkout.price_gift_line(
                db, line_amount_usd=line.amount_usd, data=cleaned
            )

        # No supplier-balance preflight: a paid order is never refused for the
        # supplier being short. If Waxpeer can't fund the top-up at fulfilment
        # time, the fulfiller returns a soft low-balance failure — the customer
        # keeps seeing "processing", ops gets alerted, and an admin tops up and
        # retries (mirrors the G2B low-balance path).

        # Last, so it wins over every branch above it — including the gift
        # re-price. Guarded to a merchant actor at the top of this function.
        if unit_price_usd_override is not None:
            unit_price_usd = unit_price_usd_override[index]

        items.append(
            OrderItem(
                id=new_id(),
                order_id=order_id,
                sku_id=sku.id,
                qty=line.qty,
                unit_price_usd=unit_price_usd,
                # Frozen here for the same reason as the rate (ADR-0051): the
                # hourly supplier-price job rewrites ``Sku.cost_usdt`` as
                # upstream prices move, so reporting that read it live
                # re-valued every past sale of this SKU whenever the supplier
                # moved. ``None`` on a variable line is not an omission — its
                # cost is the face value the customer chose, which
                # ``unit_price_usd`` already records.
                cost_usdt=None if sku.variable_amount else sku.cost_usdt,
                # The merchant's own quote, recorded and never consulted —
                # ``None`` on every retail line, which is what makes the
                # column's meaning readable (see its comment in ``models.py``).
                merchant_expected_price_usd=(
                    None
                    if merchant_expected_price_usd is None
                    else merchant_expected_price_usd[index]
                ),
                fulfillment_data=cleaned,
            )
        )
        total_usd += unit_price_usd * line.qty

    # 3) Per-currency total (see _compute_total_charged for the policy).
    total_charged, fx_snapshot_id = await _compute_total_charged(
        db,
        body=body,
        skus=skus,
        items=items,
        total_usd=total_usd,
        currency=currency,
    )

    # 3a) Affiliate discount. The client names a code; the server decides
    # whether it applies and by how much. An unusable code is ignored rather
    # than raised — see OrderCreate.affiliate_code.
    affiliate_code_id: str | None = None
    discount_charged = Decimal("0")
    if body.affiliate_code:
        resolved = await affiliate_discount.resolve_code(
            db,
            code=body.affiliate_code,
            user_id=actor.user_id,
            # This function only ever builds catalog orders — a wallet top-up
            # is assembled in wallet/funding.py and never reaches here. Passed
            # explicitly so the guard stays meaningful.
            purpose="catalog",
        )
        if isinstance(resolved, affiliate_discount.ResolvedDiscount):
            discount_charged = affiliate_discount.discount_amount(
                total_charged, resolved.percent, currency
            )
            total_charged -= discount_charged
            affiliate_code_id = resolved.code_id
            # The order-level discount has to reach the line level, or every
            # margin report keeps reporting the pre-discount number. See
            # orders.revenue.
            discount_usd_total = (total_usd * resolved.percent / Decimal(100)).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
            shares = affiliate_discount.distribute_discount_usd(
                [item.unit_price_usd * item.qty for item in items], discount_usd_total
            )
            for item, share in zip(items, shares, strict=True):
                item.discount_usd = share

    # 4) Persist the order.
    created = now()
    order = Order(
        id=order_id,
        user_id=actor.user_id,
        guest_email=actor.email,
        merchant_id=actor.merchant_id,
        # Only meaningful for a signed-in buyer: a guest's address is
        # ``guest_email`` and doubles as their claim on the order.
        delivery_email=(body.delivery_email if actor.user_id is not None else None),
        status="pending_payment",
        currency=currency,
        total_usd=total_usd,
        total_charged=total_charged,
        affiliate_code_id=affiliate_code_id,
        discount_charged=discount_charged,
        fx_snapshot_id=fx_snapshot_id,
        expires_at=created + timedelta(seconds=ORDER_EXPIRY_SECONDS),
        idempotency_key=idempotency_key,
        ip_hash=ip_hash,
        ua_hash=ua_hash,
        source=source,
        items=items,
    )
    db.add(order)
    _record_event(
        db,
        order_id=order_id,
        kind="order.created",
        actor=actor,
        payload={
            "currency": currency,
            "total_usd": str(total_usd),
            "total_charged": str(total_charged),
            "discount_charged": str(discount_charged),
            "item_count": len(items),
        },
    )

    try:
        await db.flush()
    except IntegrityError as exc:
        # Concurrent request with the same idempotency key won the race — re-read.
        await db.rollback()
        replay = await _existing_idempotent_order(db, actor=actor, idempotency_key=idempotency_key)
        if replay is not None:
            return replay
        # Some other constraint, then: the key raced but the winner is gone
        # (rolled back), or the INSERT violated something that is not the
        # idempotency index at all. Carries a ``code`` because this reaches
        # ``/merchant/v1`` too, whose published error table discriminates every
        # 409 by code — an uncoded one there would be the only status a
        # machine client cannot branch on. Additive for retail, which reads
        # ``type``.
        raise ConflictError("order conflict", code="order_conflict") from exc

    # Re-load with eager relationships so callers can return the row directly.
    return await _load_order(db, order_id)


async def find_merchant_order(
    db: AsyncSession, *, merchant_id: str, merchant_order_id: str
) -> Order | None:
    """The order this merchant already placed under ``merchant_order_id``, if any.

    The machine API keys order creation on the merchant's own id rather than
    on an ``Idempotency-Key`` header (spec §9.3), and needs to answer "have I
    seen this one?" *before* pricing — otherwise a legitimate retry of an
    order placed yesterday would be refused today because the SKU has since
    gone out of stock. This is that lookup, living here because ``orders``
    owns the table, the eager-load chain and the per-actor scoping rule.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The owning merchant — the scope. Two resellers picking
            the same id is ordinary traffic, not a replay.
        merchant_order_id: Their id for this order.

    Returns:
        The order with items and events loaded, or ``None``.
    """
    return await _existing_idempotent_order(
        db,
        actor=Actor(user_id=None, email=None, merchant_id=merchant_id),
        idempotency_key=merchant_order_id,
    )


async def mark_merchant_order_paid(
    db: AsyncSession, *, order: Order, actor: Actor, request_digest: str
) -> None:
    """Move a merchant order ``pending_payment → paid``. No ``Payment`` row exists.

    A B2B order is **born paid** (spec §9.5): the money arrived by bank
    transfer days ago and is already sitting in the reseller's deposit ledger,
    so the deposit debit *is* the settlement and there is no acquirer, no
    webhook and no ``payments`` row to hang the transition off. It never
    passes through ``pending_payment`` as a resting state — the status exists
    for the microseconds between this row's INSERT and this call, both inside
    one transaction — which is also what keeps it invisible to the ten-minute
    expiry sweep.

    Lives here rather than in ``merchants`` because ``orders`` owns this table
    and its FSM; the merchant module calls it through the ``orders.api``
    facade, like every other cross-module write.

    Deliberately does **not** publish a realtime event. ``publish_order_event``
    is a no-op for a NULL ``user_id``, which every merchant order has, and
    calling it anyway would suggest a channel exists. Resellers learn about
    status through the order read (M2 Task 5) and, since M3a Task 3, through
    the outbound webhook — which is why the status-change seam is called here
    with ``publish_realtime=False``: the webhook half is the whole point, and
    the nudge half is the thing this paragraph declines.

    Args:
        db: Session. The caller owns the transaction.
        order: The freshly created merchant order.
        actor: The merchant actor that created it — recorded on the event.
        request_digest: The machine API's fingerprint of the request that
            placed this order. Recorded on the event, where the replay check
            reads it back: same ``merchant_order_id`` and same digest is a
            retry and returns this order, a different digest is a ``409``
            (spec §9.3). It rides the paid event rather than a column of its
            own because for this channel placement and payment are the same
            instant, and the timeline is already where "what was asked for"
            belongs.

    Raises:
        ConflictError: The order is not a merchant order, is not a catalog
            sale, or has already left ``pending_payment``.
    """
    if order.merchant_id is None:
        raise ConflictError("not a merchant order", extra={"order_id": order.id})
    if order.purpose != "catalog":
        raise ConflictError("not a catalog sale", extra={"purpose": order.purpose})
    if order.status != "pending_payment":
        raise ConflictError("order is not awaiting payment", extra={"status": order.status})

    moment = now()
    order.status = "paid"
    order.paid_at = moment
    order.updated_at = moment
    _record_event(
        db,
        order_id=order.id,
        kind="order.paid",
        actor=actor,
        payload={
            "settlement": "merchant_deposit",
            "merchant_order_id": order.idempotency_key,
            "request_digest": request_digest,
            "total_charged": str(order.total_charged),
            "currency": order.currency,
        },
    )
    await db.flush()
    await on_order_status_changed(db, order, publish_realtime=False)


# ---------- the status-change seam ----------


async def on_order_status_changed(
    db: AsyncSession, order: Order, *, publish_realtime: bool = True
) -> str | None:
    """Everything that follows from an order's status having just changed.

    **The one seam.** Every site that writes ``order.status`` calls this —
    here, in ``payments.service`` and in ``fulfillment.service`` — so a fourth
    consequence is added in one place rather than to three of the four sites
    that happened to be remembered. Both of those modules used to keep their
    own copy of the realtime nudge below; they now delegate here.

    Two consequences today, and they are disjoint by construction: the
    realtime nudge reaches a *retail owner*, and the webhook reaches a
    *merchant*. A merchant order has ``user_id IS NULL`` (the actor CHECK on
    ``orders`` makes the arms exclusive), so the nudge is already a no-op for
    it — which is exactly why the webhook needed a seam of its own instead of
    riding the existing publish.

    Call it **after** the status and ``updated_at`` are set and, for the
    webhook half, from inside the transaction that set them: the delivery row
    and its ``pg_notify`` ride the caller's transaction, so an order that
    rolls back tells nobody.

    Args:
        db: Session. The caller owns the transaction.
        order: The order, already carrying its new ``status`` and
            ``updated_at``.
        publish_realtime: Whether to emit the ``order.status_changed`` nudge.
            ``False`` at the two sites that deliberately do not have one — the
            fulfilment settle, which publishes ``order.delivered`` instead and
            would otherwise start sending a connected storefront a second
            event it never used to get, and the merchant paid transition,
            which has no owner to nudge (see
            :func:`mark_merchant_order_paid`). Retail behaviour is unchanged
            at every site either way.

    Returns:
        The queued delivery's id when a merchant webhook was enqueued, else
        ``None``. Callers ignore it; the tests do not.
    """
    if publish_realtime:
        await _publish_status_changed(order)
    if order.merchant_id is None:
        return None
    # Lazy: ``merchants`` imports this module (``merchants.orders`` places an
    # order through it), so a module-level import here would close the cycle.
    from yupay.modules.merchants import webhooks as merchant_webhooks

    return await merchant_webhooks.enqueue_order_status_changed(db, order)


# ---------- realtime ----------


async def _publish_status_changed(order: Order) -> None:
    """Nudge the order's owner (if any) over the realtime channel.

    No-op for guest orders (``order.user_id is None``) — that check lives in
    ``publish_order_event`` itself. Imported lazily to avoid pulling the WS
    route stack into every orders-module import.
    """
    from yupay.modules.realtime import api as realtime

    await realtime.publish_order_event(
        order.user_id,
        {
            "type": "order.status_changed",
            "orderId": order.id,
            "status": order.status,
            "at": order.updated_at.isoformat(),
        },
    )


async def _load_order(db: AsyncSession, order_id: str) -> Order:
    stmt = (
        select(Order)
        .options(*_order_load_options(), selectinload(Order.events))
        .where(Order.id == order_id)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFoundError("order not found")
    return row


async def get_order_for_actor(db: AsyncSession, order_id: str, *, actor: Actor) -> Order:
    """Look up an order. 404 if the actor doesn't own it (to avoid leaking ids)."""
    order = await _load_order(db, order_id)
    if actor.user_id is not None:
        if order.user_id != actor.user_id:
            raise NotFoundError("order not found")
    elif actor.merchant_id is not None:
        # Explicit arm rather than letting a merchant actor fall through to the
        # guest comparison below, where its NULL email would match nothing by
        # accident instead of by design.
        if order.merchant_id != actor.merchant_id:
            raise NotFoundError("order not found")
    elif order.guest_email is None or order.guest_email.lower() != (actor.email or "").lower():
        raise NotFoundError("order not found")
    # Lazy guard: if the customer is opening a stale pending order, flip it
    # to ``expired`` now instead of letting them stare at "ждём оплату" for
    # hours until the scheduler tick gets around to it.
    if await _expire_order_inline(db, order):
        await db.flush()
    return order


async def list_orders_for_actor(db: AsyncSession, *, actor: Actor, limit: int = 50) -> list[Order]:
    """List an actor's own sales, newest first.

    Scoped by a positive match on the actor's arm, never by a comparison that
    happens to fail: SQLAlchemy compiles ``Order.guest_email == None`` to
    ``guest_email IS NULL``, which *matches* rather than excludes, so an arm
    that fell through to the guest branch would be handed every user's and
    every merchant's orders instead of none of them.

    Wallet top-ups are filtered out (``IS_SALE``) — they are funding rows, not
    purchases, and the customer's order history must not show them. Anything
    still ``pending_payment`` past its ``expires_at`` is flipped to ``expired``
    inline, so the caller never renders a stale status while waiting for the
    scheduler tick.

    Args:
        db: Open async session.
        actor: Whose orders to list — user, guest, or merchant.
        limit: Maximum rows to return, newest first.

    Returns:
        The actor's orders, newest first, with items eager-loaded.
    """
    stmt = (
        select(Order)
        .options(*_order_load_options())
        .where(IS_SALE)
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    if actor.user_id is not None:
        stmt = stmt.where(Order.user_id == actor.user_id)
    elif actor.merchant_id is not None:
        stmt = stmt.where(Order.merchant_id == actor.merchant_id)
    else:
        stmt = stmt.where(Order.guest_email == actor.email)
    rows = list((await db.execute(stmt)).scalars().all())
    # Same lazy-expiry as ``get_order_for_actor``: anything the customer is
    # looking at right now should reflect reality, not "ждём оплату · 4 days".
    changed = False
    for order in rows:
        if await _expire_order_inline(db, order):
            changed = True
    if changed:
        await db.flush()
    return rows


async def claim_orders_for_user(db: AsyncSession, *, user: User) -> int:
    """Reassign the user's guest orders to their account.

    Reassigns every order where ``guest_email`` equals the user's email, the
    order is still a guest order (``user_id IS NULL``), and the user's email is
    verified. Sets ``user_id`` and nulls ``guest_email`` in one statement so the
    ``ck_orders_actor_exclusive`` XOR CHECK always holds. Idempotent. Returns the
    number of orders claimed.
    """
    if user.email_verified_at is None or user.email is None:
        return 0
    result = await db.execute(
        update(Order)
        .where(
            Order.user_id.is_(None),
            func.lower(Order.guest_email) == user.email.lower(),
        )
        .values(user_id=user.id, guest_email=None)
    )
    return result.rowcount or 0  # type: ignore[attr-defined]


#: An order that is paid but not yet delivered is normal for a minute or two.
#: Past this it means something needs a human — a supplier failure, an exhausted
#: balance, a task that was never created at all.
STUCK_STATUSES: Final[frozenset[str]] = frozenset({"paid", "fulfilling", "fulfilled"})


async def list_stuck_paid_orders(db: AsyncSession, *, older_than_minutes: int) -> list[Order]:
    """Orders the customer has paid for and still has not received.

    Deliberately keyed on the ORDER, not on a failed fulfillment task. A task
    that failed is only one way to get here: the July-23 order on production had
    no task at all, so a task-shaped query would have reported all clear while a
    paid customer waited. Anything that has taken the money and not delivered
    belongs in this list, whatever the reason.
    """
    cutoff = now() - timedelta(minutes=older_than_minutes)
    stmt = (
        select(Order)
        .where(
            Order.status.in_(STUCK_STATUSES),
            Order.delivered_at.is_(None),
            Order.paid_at.is_not(None),
            Order.paid_at <= cutoff,
        )
        .order_by(Order.paid_at)
    )
    return list((await db.execute(stmt)).unique().scalars().all())


def _admin_search_clause(q: str) -> ColumnElement[bool] | None:
    """Build the ``q`` predicate for the admin order list, or None if unusable.

    Every branch is index-backed, because this table grows by thousands of rows
    a day and support searches it all day long:

    - a full UUID hits the ``orders`` primary key or ``ix_orders_user_created``;
    - anything else is treated as an id fragment and matched as a prefix, which
      is what ``ix_orders_id_prefix`` (``id::text text_pattern_ops``) exists for
      — it is the shape an operator produces by copying the truncated id shown
      in the table;
    - a string containing ``@`` is matched as an email substring via the
      ``ix_orders_guest_email_trgm`` trigram index, so a partial address from a
      support ticket still finds the order.

    Shorter than three characters is rejected rather than run: a one-character
    prefix matches a sixteenth of the table and is never what someone meant.
    """
    term = q.strip()
    if len(term) < 3:
        return None
    with suppress(ValueError):
        canonical = str(uuid.UUID(term))
        return or_(Order.id == canonical, Order.user_id == canonical)
    if "@" in term:
        # Spelled to match ``ix_orders_guest_email_trgm`` exactly: an expression
        # index is only used by a predicate of the same shape, so ``ILIKE`` on
        # the CITEXT column would quietly fall back to a sequential scan.
        return func.lower(cast(Order.guest_email, Text)).like(f"%{term.lower()}%")
    return cast(Order.id, Text).like(f"{term.lower()}%")


async def list_orders_admin(
    db: AsyncSession,
    *,
    status_filter: str | None = None,
    q: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Order], int]:
    """Paged admin listing. Returns ``(rows, total_matching_filter)``.

    ``since``/``until`` filter on ``Order.created_at`` (inclusive on both
    ends), mirroring the audit feed's date-range convention. ``q`` searches
    order id, owner id and guest email — see ``_admin_search_clause``.
    """
    base = select(Order).options(*_order_load_options(), selectinload(Order.events))
    count_stmt = select(func.count()).select_from(Order)
    if status_filter is not None:
        base = base.where(Order.status == status_filter)
        count_stmt = count_stmt.where(Order.status == status_filter)
    if q is not None and q.strip():
        # An unusable term must narrow to nothing, not silently widen to
        # "every order" — an operator seeing the full list would read it as
        # "the search matched everything".
        search = _admin_search_clause(q)
        clause = false() if search is None else search
        base = base.where(clause)
        count_stmt = count_stmt.where(clause)
    if since is not None:
        base = base.where(Order.created_at >= since)
        count_stmt = count_stmt.where(Order.created_at >= since)
    if until is not None:
        base = base.where(Order.created_at <= until)
        count_stmt = count_stmt.where(Order.created_at <= until)
    rows = list(
        (await db.execute(base.order_by(Order.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    return rows, total


async def get_order_admin(db: AsyncSession, order_id: str) -> Order:
    return await _load_order(db, order_id)


#: Statuses an order may be closed as ``failed`` from: the customer has paid
#: but the goods never reached them. Deliberately excludes ``pending_payment``
#: (that is ``cancel_order_admin`` — nothing was charged) and ``delivered``
#: (the customer holds the goods; reversing that is a refund, which moves real
#: money through ``payments.refund_admin``).
#:
#: Public because it has two callers and one meaning. Besides
#: :func:`mark_order_failed_admin`, ``fulfillment.service`` reads it before an
#: automatic merchant refund closes the order it has just settled (M3c Task 6),
#: and "which states is a paid-but-undeliverable order closable from" is one
#: question: a second spelling of it in another module is how the two would
#: start disagreeing about ``delivered``.
FAILABLE_STATUSES: Final[frozenset[str]] = frozenset({"paid", "fulfilling", "fulfilled"})


async def mark_order_failed_admin(
    db: AsyncSession, order_id: str, *, admin_id: str, reason: str
) -> Order:
    """Close a paid-but-undeliverable order as ``failed``.

    The one manual status change we expose. It is intent-based rather than a
    free-form status setter because order status drives money and goods: a raw
    write could mark an order ``delivered`` without ever creating a
    ``Delivery`` (customer sees "delivered", gets no codes), or ``paid`` with
    no payment row (the fulfilment saga starts from the payment path, so the
    order would simply stall). Here the state is only ever moved *backwards*
    into a terminal failure, and the cascade below keeps the invariants:

    * open fulfilment tasks are cancelled, so a "failed" order cannot still
      hand out codes a moment later;
    * pending / requires_action payments are closed, so nothing lingers in the
      payments triage queue with no customer behind it.

    Money is **not** moved: a refund is a separate, explicit admin action.

    Args:
        db: Async session.
        order_id: Order to close.
        admin_id: Acting admin, recorded on the audit event.
        reason: Why it was closed. Required — "who failed this and why" has to
            be answerable from the order timeline alone.

    Raises:
        NotFoundError: Unknown order.
        ConflictError: Order is not in a status this action may close.
    """
    order = await _load_order(db, order_id)
    if order.status not in FAILABLE_STATUSES:
        raise ConflictError(
            "cannot mark order failed in current status",
            extra={"status": order.status, "allowed": sorted(FAILABLE_STATUSES)},
        )

    # Fulfilment cascade FIRST, before any write to the order row (the status
    # write, the OrderEvent insert's FOR KEY SHARE, and the payment cascade
    # whose autoflush would emit them). System-wide lock order: **fulfilment
    # task rows before the order row, everywhere** — see the same comment in
    # ``payments.service._apply_refund_reversal``. Everything below commits
    # atomically, so the end state is identical either way; only the lock
    # order changes. Lazy import avoids the orders.service ↔
    # fulfillment.service cycle.
    from yupay.modules.fulfillment import service as fulfillment_svc

    await fulfillment_svc.cancel_open_tasks_for_order(db, order_id=order_id, reason="order_failed")

    moment = now()
    order.status = "failed"
    order.updated_at = moment
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order_id,
            kind="order.failed",
            payload={"by": "admin", "reason": reason},
            actor=f"admin:{admin_id}",
        )
    )
    await _cascade_cancel_open_payments(
        db, order_id=order_id, reason="order_failed", actor=f"admin:{admin_id}"
    )
    await db.flush()
    await on_order_status_changed(db, order)
    return order


async def cancel_order_admin(db: AsyncSession, order_id: str, *, admin_id: str) -> Order:
    """Admin-initiated cancellation. Only legal from ``pending_payment``."""
    order = await _load_order(db, order_id)
    if order.status != "pending_payment":
        raise ConflictError(
            "cannot cancel order in current status",
            extra={"status": order.status},
        )
    # Stop any in-flight fulfilment for the cancelled order. Today cancel is
    # only legal from ``pending_payment`` (no task exists yet), so this is a
    # no-op; it keeps the invariant "a terminated order has no open fulfilment
    # task" if the cancel window is ever widened. It goes first for the same
    # reason as in ``mark_order_failed_admin``: fulfilment task rows are
    # locked before the order row, everywhere — including on a path where
    # today it cannot matter, so that widening the cancel window later does
    # not quietly reintroduce the inversion. Lazy import avoids the
    # orders.service ↔ fulfillment.service import cycle.
    from yupay.modules.fulfillment import service as fulfillment_svc

    await fulfillment_svc.cancel_open_tasks_for_order(
        db, order_id=order_id, reason="order_cancelled"
    )

    order.status = "cancelled"
    order.cancelled_at = now()
    order.updated_at = order.cancelled_at
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order_id,
            kind="order.cancelled",
            payload={"by": "admin"},
            actor=f"admin:{admin_id}",
        )
    )
    await _cascade_cancel_open_payments(
        db, order_id=order_id, reason="order_cancelled", actor=f"admin:{admin_id}"
    )
    await db.flush()
    await on_order_status_changed(db, order)
    return order


async def _cascade_cancel_open_payments(
    db: AsyncSession, *, order_id: str, reason: str, actor: str
) -> int:
    """Close any pending/requires_action payments tied to a terminating order.

    Without this an expired order leaves a payment row in ``pending`` forever,
    which then shows up in /admin/payments/triage as a stuck payment that
    nobody can actually resolve — there's no customer on the other side. We
    record a ``PaymentAttempt`` row for each cancelled payment so the audit
    trail (and ``audit_feed``) reflects who terminated it and why.
    """
    stmt = select(Payment).where(
        Payment.order_id == order_id,
        Payment.status.in_(("pending", "requires_action")),
    )
    payments = list((await db.execute(stmt)).scalars().all())
    moment = now()
    for payment in payments:
        payment.status = "cancelled"
        payment.updated_at = moment
        db.add(
            PaymentAttempt(
                id=new_id(),
                payment_id=payment.id,
                kind="cancel",
                status="ok",
                payload={"trigger": "order_terminated", "reason": reason, "actor": actor},
            )
        )
    if payments:
        db.add(
            OrderEvent(
                id=new_id(),
                order_id=order_id,
                kind="payments.cascaded_cancel",
                payload={"count": len(payments), "reason": reason},
                actor=actor,
            )
        )
    return len(payments)


async def _expire_order_inline(db: AsyncSession, order: Order) -> bool:
    """Flip a single ``pending_payment`` order to ``expired`` if its TTL
    elapsed. Used as a lazy guard inside read paths so the customer sees the
    real status the moment they open the order, without waiting on the
    scheduler tick. Returns ``True`` if a transition was applied.

    Cascade: any open payment intent on the order is cancelled too — see
    :func:`_cascade_cancel_open_payments`.
    """
    if order.status != "pending_payment":
        return False
    if order.expires_at > now():
        return False
    order.status = "expired"
    order.cancelled_at = now()
    order.updated_at = order.cancelled_at
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind="order.expired",
            payload={"reason": "payment_window_elapsed"},
            actor="system:expiry",
        )
    )
    await _cascade_cancel_open_payments(
        db, order_id=order.id, reason="order_expired", actor="system:expiry"
    )
    # Immediate realtime push (in-transaction, not after-commit) — same
    # rationale as the fulfilment saga: the client re-fetches on the nudge, so
    # a rare rollback after this point self-corrects on that refetch.
    await on_order_status_changed(db, order)
    return True


async def expire_stale_orders(db: AsyncSession, *, batch_limit: int = 500) -> int:
    """Bulk-flip all ``pending_payment`` orders whose TTL elapsed to
    ``expired`` and emit an audit event for each.

    Called from the scheduler (every minute) — the lazy in-request guard
    already covers orders the customer actively looks at, this one cleans
    up the long tail of abandoned carts so the admin dashboard stays
    honest.

    ``batch_limit`` bounds the per-tick fan-out so a backlog doesn't pin
    the worker on a single iteration; the next tick picks up the rest.
    """
    stmt = (
        select(Order)
        .where(Order.status == "pending_payment", Order.expires_at <= now())
        .order_by(Order.expires_at.asc())
        .limit(batch_limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    flipped = 0
    for order in rows:
        if await _expire_order_inline(db, order):
            flipped += 1
    if flipped:
        await db.flush()
    return flipped


__all__ = [
    "FAILABLE_STATUSES",
    "ORDER_EXPIRY_SECONDS",
    "Actor",
    "build_item_display",
    "cancel_order_admin",
    "claim_orders_for_user",
    "create_order",
    "expire_stale_orders",
    "get_order_admin",
    "get_order_for_actor",
    "list_orders_admin",
    "list_orders_for_actor",
    "list_stuck_paid_orders",
    "succeeded_provider_for",
]
