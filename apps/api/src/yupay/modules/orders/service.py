"""Order service: create, get, list. Status transitions land here too."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.config import Settings
from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Product, Sku
from yupay.modules.fx.factory import build_default_service
from yupay.modules.orders.models import Order, OrderEvent, OrderItem
from yupay.modules.orders.schemas import OrderCreate
from yupay.modules.orders.validation import validate_fulfillment_data

if TYPE_CHECKING:
    from yupay.modules.fx.service import FxService

ORDER_EXPIRY_SECONDS = 30 * 60  # 30 min — see ADR-0011


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
    actor_label = (
        f"user:{actor.user_id}" if actor.user_id else f"guest:{actor.email}"
    )
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order_id,
            kind=kind,
            payload=payload or {},
            actor=actor_label,
        )
    )


async def _fetch_skus_with_product(
    db: AsyncSession, sku_ids: list[str]
) -> dict[str, Sku]:
    """Load all referenced SKUs along with their product (for required_fields)."""
    if not sku_ids:
        return {}
    stmt = (
        select(Sku)
        .options(selectinload(Sku.product))
        .where(Sku.id.in_(sku_ids))
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {s.id: s for s in rows}


async def _existing_idempotent_order(
    db: AsyncSession, *, actor: Actor, idempotency_key: str
) -> Order | None:
    stmt = (
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.events))
        .where(Order.idempotency_key == idempotency_key)
    )
    if actor.user_id is not None:
        stmt = stmt.where(Order.user_id == actor.user_id)
    else:
        stmt = stmt.where(Order.guest_email == actor.email)
    return (await db.execute(stmt)).scalar_one_or_none()


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
    existing = await _existing_idempotent_order(
        db, actor=actor, idempotency_key=idempotency_key
    )
    if existing is not None:
        return existing

    # 1) Load SKUs once.
    sku_ids = [item.sku_id for item in body.items]
    skus = await _fetch_skus_with_product(db, sku_ids)
    missing = [sid for sid in sku_ids if sid not in skus or not skus[sid].active]
    if missing:
        raise ValidationError(
            "unknown or inactive SKU", extra={"sku_ids": missing}
        )

    # 2) Build order items with frozen price + validated fulfillment_data.
    order_id = new_id()
    items: list[OrderItem] = []
    total_usd = Decimal("0")
    for line in body.items:
        sku = skus[line.sku_id]
        product: Product = sku.product
        cleaned = validate_fulfillment_data(product=product, data=line.fulfillment_data)
        items.append(
            OrderItem(
                id=new_id(),
                order_id=order_id,
                sku_id=sku.id,
                qty=line.qty,
                unit_price_usd=sku.price_usd,
                fulfillment_data=cleaned,
            )
        )
        total_usd += sku.price_usd * line.qty

    # 3) FX snapshot for non-USD orders.
    currency = body.currency.upper()
    fx_snapshot_id: str | None = None
    if currency == "USD":
        total_charged = total_usd
    else:
        factory = fx_service_factory or build_default_service
        fx = factory()
        snap = await fx.snapshot(db, base="USD", quote=currency)
        fx_snapshot_id = snap.id
        total_charged = (total_usd * snap.rate).quantize(Decimal("1.000000"))

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
        replay = await _existing_idempotent_order(
            db, actor=actor, idempotency_key=idempotency_key
        )
        if replay is not None:
            return replay
        raise ConflictError("order conflict") from exc

    # Re-load with eager relationships so callers can return the row directly.
    return await _load_order(db, order_id)


async def _load_order(db: AsyncSession, order_id: str) -> Order:
    stmt = (
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.events))
        .where(Order.id == order_id)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFoundError("order not found")
    return row


async def get_order_for_actor(
    db: AsyncSession, order_id: str, *, actor: Actor
) -> Order:
    """Look up an order. 404 if the actor doesn't own it (to avoid leaking ids)."""
    order = await _load_order(db, order_id)
    if actor.user_id is not None:
        if order.user_id != actor.user_id:
            raise NotFoundError("order not found")
    elif order.guest_email is None or order.guest_email.lower() != (
        actor.email or ""
    ).lower():
        raise NotFoundError("order not found")
    return order


async def list_orders_for_actor(
    db: AsyncSession, *, actor: Actor, limit: int = 50
) -> list[Order]:
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    if actor.user_id is not None:
        stmt = stmt.where(Order.user_id == actor.user_id)
    else:
        stmt = stmt.where(Order.guest_email == actor.email)
    return list((await db.execute(stmt)).scalars().all())


async def list_orders_admin(
    db: AsyncSession,
    *,
    status_filter: str | None = None,
    limit: int = 50,
) -> list[Order]:
    stmt = (
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.events))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    if status_filter is not None:
        stmt = stmt.where(Order.status == status_filter)
    return list((await db.execute(stmt)).scalars().all())


async def get_order_admin(db: AsyncSession, order_id: str) -> Order:
    return await _load_order(db, order_id)


async def cancel_order_admin(
    db: AsyncSession, order_id: str, *, admin_id: str
) -> Order:
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
    await db.flush()
    return order


__all__ = [
    "ORDER_EXPIRY_SECONDS",
    "Actor",
    "cancel_order_admin",
    "create_order",
    "get_order_admin",
    "get_order_for_actor",
    "list_orders_admin",
    "list_orders_for_actor",
]
