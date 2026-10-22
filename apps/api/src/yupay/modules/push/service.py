"""The buyer's devices, and queueing a push when one of their orders settles.

Queueing rides the transaction that changed the order (``orders.service.on_order_status_changed``
calls :func:`enqueue_for_order`), so an order that rolls back pushes nothing. Sending is the
worker's: :mod:`yupay.modules.push.delivery`.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import and_, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from yupay.core.clock import now
from yupay.core.errors import NotFoundError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import BrandTranslation, Product, Sku
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.push import texts
from yupay.modules.push.models import PushDevice, PushMessage
from yupay.modules.users.models import User

log = get_logger("yupay.push")

PUSH_QUEUE_CHANNEL: Final = "push_queue"


async def register_device(
    db: AsyncSession, *, user_id: str, token: str, platform: str, app_version: str | None
) -> PushDevice:
    """Create or refresh the device behind ``token`` for ``user_id``.

    A token already held by another account moves here: the phone changed hands (or accounts),
    and the previous account must stop receiving this phone's pushes. Registering re-enables a
    device that was signed out.
    """
    device = (
        await db.execute(select(PushDevice).where(PushDevice.token == token).with_for_update())
    ).scalar_one_or_none()
    if device is None:
        device = PushDevice(id=new_id(), user_id=user_id, token=token, platform=platform)
        db.add(device)
    elif device.user_id != user_id:
        log.info("push.device.moved", device_id=device.id)
        device.user_id = user_id
    device.platform = platform
    device.app_version = app_version
    device.last_seen_at = now()
    device.disabled_at = None
    device.disabled_reason = None
    await db.flush()
    return device


async def disable_device(db: AsyncSession, *, user_id: str, device_id: str) -> PushDevice:
    """Stop pushing to one of the account's devices (sign-out).

    Raises:
        NotFoundError: No such device on this account.
    """
    device = await db.get(PushDevice, device_id)
    if device is None or device.user_id != user_id:
        raise NotFoundError("push device not found")
    if device.disabled_at is None:
        device.disabled_at = now()
        device.disabled_reason = "signed_out"
        await db.flush()
    return device


async def active_devices(db: AsyncSession, *, user_id: str) -> list[PushDevice]:
    """The account's devices that may be pushed to, newest first."""
    rows = await db.execute(
        select(PushDevice)
        .where(PushDevice.user_id == user_id, PushDevice.disabled_at.is_(None))
        .order_by(PushDevice.last_seen_at.desc())
    )
    return list(rows.scalars())


def _kind_for(order: Order) -> str | None:
    if order.status == "delivered":
        return texts.WALLET_CREDITED if order.purpose == "wallet_topup" else texts.ORDER_DELIVERED
    if order.status == "failed":
        return texts.ORDER_FAILED
    if order.status == "refunded":
        return texts.ORDER_REFUNDED
    return None


async def _what(db: AsyncSession, order: Order, locale: str) -> str:
    """The order's brand and how many more lines it has, read without touching relationships.

    A plain query rather than ``order.items``: this runs inside other modules' transactions,
    where a lazy load on an async session raises.
    """
    wanted = aliased(BrandTranslation)
    fallback = aliased(BrandTranslation)
    row = (
        await db.execute(
            select(func.coalesce(wanted.name, fallback.name), func.count().over())
            .select_from(OrderItem)
            .join(Sku, Sku.id == OrderItem.sku_id)
            .join(Product, Product.id == Sku.product_id)
            .outerjoin(wanted, and_(wanted.brand_id == Product.brand_id, wanted.locale == locale))
            .outerjoin(
                fallback, and_(fallback.brand_id == Product.brand_id, fallback.locale == "ru")
            )
            .where(OrderItem.order_id == order.id)
            .order_by(OrderItem.created_at, OrderItem.id)
            .limit(1)
        )
    ).first()
    brand, lines = (row[0], int(row[1])) if row is not None else (None, 0)
    return texts.what(brand=brand, extra_lines=max(lines - 1, 0), order_id=order.id, locale=locale)


async def enqueue_for_order(db: AsyncSession, order: Order) -> int:
    """Queue a push to every device of the order's buyer, if its new status is one they wait for.

    Delivered, failed and refunded, and a credited wallet top-up. Nothing for a merchant or a
    guest order (no account, no device). Never raises: a push is a courtesy, and the order's
    own write must commit whatever happens here.

    Returns:
        How many messages were queued.
    """
    kind = _kind_for(order)
    if kind is None or order.user_id is None:
        return 0
    try:
        async with db.begin_nested():
            return await _enqueue(db, order, kind)
    except (IntegrityError, DataError):
        log.exception("push.enqueue_failed", order_id=order.id, kind=kind)
        return 0


async def _enqueue(db: AsyncSession, order: Order, kind: str) -> int:
    assert order.user_id is not None  # checked by the caller
    devices = await active_devices(db, user_id=order.user_id)
    if not devices:
        return 0
    locale = (await db.execute(select(User.locale).where(User.id == order.user_id))).scalar()
    if kind == texts.WALLET_CREDITED:
        title, body = texts.render(kind, locale, amount=texts.amount(order.total_charged))
    else:
        title, body = texts.render(kind, locale, what=await _what(db, order, locale or "ru"))
    rows = [
        {
            "id": new_id(),
            "device_id": device.id,
            "user_id": order.user_id,
            "kind": kind,
            "dedupe_key": f"{kind}:{order.id}",
            "title": title,
            "body": body,
            "data": {"type": "order", "order_id": order.id},
        }
        for device in devices
    ]
    inserted = (
        await db.execute(
            insert(PushMessage)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_push_messages_device_id_dedupe_key")
            .returning(PushMessage.id)
        )
    ).scalars()
    queued = list(inserted)
    if queued:
        await db.execute(
            text("SELECT pg_notify(:channel, :id)"),
            {"channel": PUSH_QUEUE_CHANNEL, "id": queued[0]},
        )
        log.info("push.queued", order_id=order.id, kind=kind, messages=len(queued))
    return len(queued)
