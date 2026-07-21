"""Order service: create, get, list. Status transitions land here too."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import (
    ConflictError,
    NotFoundError,
    UpstreamUnavailableError,
    ValidationError,
)
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.fulfillment.suppliers import WaxpeerFulfiller, get_fulfiller
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.service import FxUnavailableError
from yupay.modules.orders.models import Order, OrderEvent, OrderItem
from yupay.modules.orders.schemas import OrderCreate, OrderItemDisplay, OrderItemIn
from yupay.modules.orders.validation import validate_fulfillment_data
from yupay.modules.payments.models import Payment, PaymentAttempt
from yupay.modules.pricing.fx_guard import RateRejected, guarded_usd_rate
from yupay.modules.pricing.variable import display_rate, price_in_quote, to_units, validate_amount
from yupay.modules.sourcing.service import resolve_for_sku


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
    )


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
    return OrderItemDisplay(
        brand_slug=brand.slug if brand is not None else "",
        brand_name=_tr_name(brand.translations, locale) if brand is not None else "",
        product_slug=product.slug if product is not None else "",
        product_name=_tr_name(product.translations, locale) if product is not None else "",
        product_kind=product.kind if product is not None else "voucher",
        sku_code=sku.sku_code,
        denomination=sku.denomination,
        region=sku.region,
        image_url=sku.image_url or (product.image_url if product is not None else None),
    )


if TYPE_CHECKING:
    from yupay.modules.fx.service import FxService

# Long enough to walk through a real acquirer hop (Click / Payme / YooKassa
# typically need 1–3 min including 3DS), short enough that an abandoned cart
# doesn't squat the inventory reservation. 10 minutes matches the median
# checkout-to-confirm time on UZ acquirers we've measured.
ORDER_EXPIRY_SECONDS = 10 * 60


@dataclass(frozen=True)
class Actor:
    """Either a logged-in user (``user_id``) or a guest (``email``). Exactly one set."""

    user_id: str | None
    email: str | None

    def __post_init__(self) -> None:
        if (self.user_id is None) == (self.email is None):
            raise ValidationError("actor must be exactly one of user_id / email")


def _record_event(
    db: AsyncSession,
    *,
    order_id: str,
    kind: str,
    actor: Actor,
    payload: dict[str, object] | None = None,
) -> None:
    actor_label = f"user:{actor.user_id}" if actor.user_id else f"guest:{actor.email}"
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
            selectinload(Sku.price_overrides),
        )
        .where(Sku.id.in_(sku_ids))
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {s.id: s for s in rows}


def _sku_is_buyable(sku: Sku) -> bool:
    """A SKU is buyable only when it and its whole product → brand chain are
    active. Requires ``sku.product`` and ``sku.product.brand`` eager-loaded."""
    product = sku.product
    brand = product.brand if product is not None else None
    return bool(sku.active and product is not None and product.active and brand and brand.active)


async def _existing_idempotent_order(
    db: AsyncSession, *, actor: Actor, idempotency_key: str
) -> Order | None:
    stmt = (
        select(Order)
        .options(*_order_load_options(), selectinload(Order.events))
        .where(Order.idempotency_key == idempotency_key)
    )
    if actor.user_id is not None:
        stmt = stmt.where(Order.user_id == actor.user_id)
    else:
        stmt = stmt.where(Order.guest_email == actor.email)
    return (await db.execute(stmt)).scalar_one_or_none()


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
        ValidationError: ``amount_usd`` is missing/out of bounds for a
            variable SKU, present for a fixed one, or the line is a
            variable-amount SKU with ``qty != 1`` or ``currency == "USD"``.
    """
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
        validate_amount(
            line.amount_usd,
            minimum=sku.min_amount_usd or Decimal("0"),
            maximum=sku.max_amount_usd or Decimal("0"),
        )
        return line.amount_usd
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
) -> Decimal:
    """Amount charged, in ``currency``, for one variable-amount line.

    Never uses a ``SkuPrice`` override or the plain FX snapshot — only the
    guarded rate times the SKU's own margin multiplier. ``rate_cache``
    memoizes the guarded market rate per currency across an order's lines:
    every variable line in the same currency shares the same market rate
    (only the multiplier differs per SKU), so this avoids re-querying the
    FX trust gate once per line.

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
    return price_in_quote(unit_price_usd, rate=rate) * qty


async def _compute_total_charged(
    db: AsyncSession,
    *,
    body: OrderCreate,
    skus: dict[str, Sku],
    items: list[OrderItem],
    total_usd: Decimal,
    currency: str,
    fx_service_factory: Callable[[], FxService] | None,
) -> tuple[Decimal, str | None]:
    """Per-currency total. Catalog already returned a native price for SKUs
    that have a ``SkuPrice`` override in the order currency — checkout must
    charge that exact figure, otherwise the user sees one number in the
    package picker and a different (FX-derived) one at submit. Falls back to
    a live FX rate only when no override exists for the selected currency;
    variable-amount lines never use either path (see
    :func:`_variable_line_charge`).

    The ``currency == "USD"`` short-circuit below is only safe because
    ``_resolve_line_unit_price`` already refused any variable-amount line
    paired with ``currency == "USD"`` — by the time an order reaches this
    function, USD + variable-amount can no longer coexist, so face-value
    ``total_usd`` is never mistaken for a margin-bearing price on one of
    those lines.

    Returns:
        ``(total_charged, fx_snapshot_id)`` — ``fx_snapshot_id`` stays
        ``None`` when every line was priced from an override, USD, or a
        variable-amount line's own guarded rate.
    """
    if currency == "USD":
        return total_usd, None

    total_charged = Decimal("0")
    fx_snapshot_id: str | None = None
    fx_snap = None
    rate_cache: dict[str, Decimal] = {}
    for line, item in zip(body.items, items, strict=True):
        sku = skus[line.sku_id]

        if sku.variable_amount:
            total_charged += await _variable_line_charge(
                db,
                sku=sku,
                unit_price_usd=item.unit_price_usd,
                qty=line.qty,
                currency=currency,
                rate_cache=rate_cache,
            )
            continue

        override = next(
            (o for o in sku.price_overrides if o.currency.upper() == currency),
            None,
        )
        if override is not None:
            total_charged += override.price * line.qty
            continue
        if fx_snap is None:
            factory = fx_service_factory or build_default_service
            fx = factory()
            try:
                fx_snap = await fx.snapshot(db, base="USD", quote=currency)
            except FxUnavailableError as exc:
                raise UpstreamUnavailableError(
                    f"Не удалось получить курс USD→{currency}. Попробуйте позже или "
                    "оплатите в USD.",
                    base="USD",
                    quote=currency,
                ) from exc
            fx_snapshot_id = fx_snap.id
        total_charged += (sku.price_usd * line.qty * fx_snap.rate).quantize(Decimal("1.000000"))

    return total_charged, fx_snapshot_id


async def _preflight_variable_supplier_balance(
    db: AsyncSession, *, sku: Sku, unit_price_usd: Decimal, qty: int
) -> None:
    """Refuse a variable-amount line before we take the customer's money if
    the supplier we'd route it to cannot actually fund it.

    Only Waxpeer (Steam wallet top-ups) is preflighted today — a no-op for
    fixed SKUs and for anything else ``sourcing.resolve_for_sku`` decides on,
    same as :meth:`G2bFulfiller._check_balance_or_none` does inside its own
    adapter for G2B. We must not accept payment for a top-up we cannot
    deliver; catching this at checkout is cheaper than a stuck fulfilment
    task and a refund.
    """
    if not sku.variable_amount:
        return
    decision = await resolve_for_sku(db, sku.id)
    if decision.primary != "supplier:waxpeer":
        return
    fulfiller = get_fulfiller("waxpeer")
    if not isinstance(fulfiller, WaxpeerFulfiller):
        return
    needed = to_units(unit_price_usd, fee_rate=get_settings().waxpeer_fee_rate)
    if not await fulfiller.has_balance(needed * qty):
        raise UpstreamUnavailableError(
            "Пополнение временно недоступно. Попробуйте позже.",
            supplier="waxpeer",
        )


async def create_order(
    db: AsyncSession,
    body: OrderCreate,
    *,
    actor: Actor,
    idempotency_key: str,
    settings: Settings | None = None,  # noqa: ARG001 -- reserved for future per-request config
    fx_service_factory: Callable[[], FxService] | None = None,
    ip_hash: str | None = None,
    ua_hash: str | None = None,
) -> Order:
    """Validate, snapshot price + FX, persist the order. Idempotent per actor.

    Returns the persisted order (with items + events loaded).
    """
    existing = await _existing_idempotent_order(db, actor=actor, idempotency_key=idempotency_key)
    if existing is not None:
        return existing

    # 1) Load SKUs once. A line is buyable only if the whole SKU → product →
    # brand chain is active — deactivating a brand doesn't cascade to its
    # SKUs, so checking only ``sku.active`` would let a hidden brand's product
    # still be paid for.
    sku_ids = [item.sku_id for item in body.items]
    skus = await _fetch_skus_with_product(db, sku_ids)
    missing = [sid for sid in sku_ids if sid not in skus or not _sku_is_buyable(skus[sid])]
    if missing:
        raise ValidationError("unknown or inactive SKU", extra={"sku_ids": missing})

    # 2) Build order items with frozen price + validated fulfillment_data.
    # Resolved once, up front, so the variable-amount×USD guard in
    # _resolve_line_unit_price sees the real order currency for every line.
    currency = body.currency.upper()
    order_id = new_id()
    items: list[OrderItem] = []
    total_usd = Decimal("0")
    for line in body.items:
        sku = skus[line.sku_id]
        product: Product = sku.product
        cleaned = validate_fulfillment_data(product=product, data=line.fulfillment_data)
        unit_price_usd = _resolve_line_unit_price(sku, line, currency)

        await _preflight_variable_supplier_balance(
            db, sku=sku, unit_price_usd=unit_price_usd, qty=line.qty
        )

        items.append(
            OrderItem(
                id=new_id(),
                order_id=order_id,
                sku_id=sku.id,
                qty=line.qty,
                unit_price_usd=unit_price_usd,
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
        fx_service_factory=fx_service_factory,
    )

    # 4) Persist the order.
    created = now()
    order = Order(
        id=order_id,
        user_id=actor.user_id,
        guest_email=actor.email,
        status="pending_payment",
        currency=currency,
        total_usd=total_usd,
        total_charged=total_charged,
        fx_snapshot_id=fx_snapshot_id,
        expires_at=created + timedelta(seconds=ORDER_EXPIRY_SECONDS),
        idempotency_key=idempotency_key,
        ip_hash=ip_hash,
        ua_hash=ua_hash,
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
        raise ConflictError("order conflict") from exc

    # Re-load with eager relationships so callers can return the row directly.
    return await _load_order(db, order_id)


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
    elif order.guest_email is None or order.guest_email.lower() != (actor.email or "").lower():
        raise NotFoundError("order not found")
    # Lazy guard: if the customer is opening a stale pending order, flip it
    # to ``expired`` now instead of letting them stare at "ждём оплату" for
    # hours until the scheduler tick gets around to it.
    if await _expire_order_inline(db, order):
        await db.flush()
    return order


async def list_orders_for_actor(db: AsyncSession, *, actor: Actor, limit: int = 50) -> list[Order]:
    stmt = (
        select(Order).options(*_order_load_options()).order_by(Order.created_at.desc()).limit(limit)
    )
    if actor.user_id is not None:
        stmt = stmt.where(Order.user_id == actor.user_id)
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


async def list_orders_admin(
    db: AsyncSession,
    *,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Order], int]:
    """Paged admin listing. Returns ``(rows, total_matching_filter)``."""
    base = select(Order).options(*_order_load_options(), selectinload(Order.events))
    count_stmt = select(func.count()).select_from(Order)
    if status_filter is not None:
        base = base.where(Order.status == status_filter)
        count_stmt = count_stmt.where(Order.status == status_filter)
    rows = list(
        (await db.execute(base.order_by(Order.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    return rows, total


async def get_order_admin(db: AsyncSession, order_id: str) -> Order:
    return await _load_order(db, order_id)


async def cancel_order_admin(db: AsyncSession, order_id: str, *, admin_id: str) -> Order:
    """Admin-initiated cancellation. Only legal from ``pending_payment``."""
    order = await _load_order(db, order_id)
    if order.status != "pending_payment":
        raise ConflictError(
            "cannot cancel order in current status",
            extra={"status": order.status},
        )
    order.status = "cancelled"
    order.cancelled_at = now()
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
    # Stop any in-flight fulfilment for the cancelled order. Today cancel is
    # only legal from ``pending_payment`` (no task exists yet), so this is a
    # no-op; it keeps the invariant "a terminated order has no open fulfilment
    # task" if the cancel window is ever widened. Lazy import avoids the
    # orders.service ↔ fulfillment.service import cycle.
    from yupay.modules.fulfillment import service as fulfillment_svc

    await fulfillment_svc.cancel_open_tasks_for_order(
        db, order_id=order_id, reason="order_cancelled"
    )
    await db.flush()
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
    "ORDER_EXPIRY_SECONDS",
    "Actor",
    "build_item_display",
    "cancel_order_admin",
    "create_order",
    "expire_stale_orders",
    "get_order_admin",
    "get_order_for_actor",
    "list_orders_admin",
    "list_orders_for_actor",
]
