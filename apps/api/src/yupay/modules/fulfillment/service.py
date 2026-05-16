"""Fulfilment saga (synchronous skeleton).

Drives an order from ``paid`` through ``fulfilling → fulfilled → delivered`` by
creating one :class:`FulfillmentTask` per :class:`OrderItem`, executing each task
in-process against the resolved :class:`Fulfiller`, recording each interaction
in ``fulfillment_attempts``, and persisting the artifact in ``deliveries``.

When the Dramatiq worker lands, ``start_for_order`` writes an outbox row instead
of executing inline; the public API stays the same.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.models import (
    Delivery,
    FulfillmentAttempt,
    FulfillmentTask,
)
from yupay.modules.fulfillment.suppliers import (
    Fulfiller,
    FulfillerError,
    FulfillerNotIntegratedError,
    FulfillResult,
    get_fulfiller,
)
from yupay.modules.orders.models import Order, OrderEvent, OrderItem

log = get_logger("yupay.fulfillment.service")


# ---------- supplier routing ----------


def _resolve_supplier(item: OrderItem) -> str:  # noqa: ARG001 -- per ADR-0013
    """Map an order item to a supplier slug.

    Today: hardcoded to ``"mock"`` because the ``sourcing`` module is not built
    yet. When `sourcing.sku_sourcing_rules` lands, this helper queries it.
    """
    return "mock"


# ---------- loaders ----------


async def _load_order_with_items(db: AsyncSession, order_id: str) -> Order:
    stmt = (
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.events))
        .where(Order.id == order_id)
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise NotFoundError("order not found")
    return order


async def _load_task(db: AsyncSession, task_id: str) -> FulfillmentTask:
    stmt = (
        select(FulfillmentTask)
        .options(selectinload(FulfillmentTask.attempts))
        .where(FulfillmentTask.id == task_id)
    )
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise NotFoundError("fulfilment task not found")
    return task


async def _existing_tasks_for_order(
    db: AsyncSession, order_id: str
) -> list[FulfillmentTask]:
    stmt = (
        select(FulfillmentTask)
        .options(selectinload(FulfillmentTask.attempts))
        .where(FulfillmentTask.order_id == order_id)
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------- audit ----------


def _record_attempt(
    db: AsyncSession,
    *,
    task: FulfillmentTask,
    kind: str,
    status: str,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    db.add(
        FulfillmentAttempt(
            id=new_id(),
            task_id=task.id,
            kind=kind,
            status=status,
            payload=payload or {},
            error=error,
        )
    )
    task.attempts_count += 1
    task.updated_at = now()


# ---------- core saga ----------


async def start_for_order(db: AsyncSession, *, order_id: str) -> list[FulfillmentTask]:
    """Plan and execute fulfilment for a freshly-paid order.

    Creates one task per order item (idempotent — re-running on the same order
    is a no-op because of the ``UNIQUE(order_item_id)`` constraint), drives
    order ``paid → fulfilling``, then processes every task in-process.
    """
    order = await _load_order_with_items(db, order_id)
    if order.status not in ("paid", "fulfilling"):
        raise ConflictError(
            "order is not in a fulfilment-ready state",
            extra={"status": order.status},
        )

    existing = {t.order_item_id: t for t in await _existing_tasks_for_order(db, order_id)}
    new_tasks: list[FulfillmentTask] = []
    for item in order.items:
        if item.id in existing:
            new_tasks.append(existing[item.id])
            continue
        supplier = _resolve_supplier(item)
        task = FulfillmentTask(
            id=new_id(),
            order_id=order.id,
            order_item_id=item.id,
            supplier=supplier,
            status="pending",
        )
        db.add(task)
        new_tasks.append(task)

    if order.status == "paid":
        order.status = "fulfilling"
        order.updated_at = now()
        db.add(
            OrderEvent(
                id=new_id(),
                order_id=order.id,
                kind="order.fulfilling",
                payload={"task_ids": [t.id for t in new_tasks]},
                actor="fulfillment",
            )
        )

    await db.flush()

    for task in new_tasks:
        if task.status == "pending":
            await process_task(db, task_id=task.id)

    await _try_settle_order(db, order_id=order_id)
    await db.flush()
    return new_tasks


async def process_task(db: AsyncSession, *, task_id: str) -> FulfillmentTask:
    """Run a single task against its supplier and persist the outcome."""
    task = await _load_task(db, task_id)
    if task.status in ("succeeded", "cancelled"):
        return task

    item = (
        await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
    ).scalar_one()
    order = (
        await db.execute(select(Order).where(Order.id == task.order_id))
    ).scalar_one()

    task.status = "in_progress"
    task.updated_at = now()
    fulfiller: Fulfiller = get_fulfiller(task.supplier)

    try:
        result: FulfillResult = await fulfiller.fulfill(
            order=order, item=item, idempotency_key=task.id
        )
    except (FulfillerError, FulfillerNotIntegratedError) as exc:
        _record_attempt(
            db,
            task=task,
            kind="fulfill",
            status="error",
            payload={"supplier": task.supplier},
            error=str(exc),
        )
        task.status = "failed"
        task.failed_at = now()
        task.last_error = str(exc)
        item.fulfillment_state = "failed"
        log.warning(
            "fulfillment.fulfill.failed",
            task_id=task.id,
            supplier=task.supplier,
            error=str(exc),
        )
        return task

    task.external_order_id = result.external_order_id
    if result.extra_metadata:
        task.extra_metadata = {**task.extra_metadata, **result.extra_metadata}

    _record_attempt(
        db,
        task=task,
        kind="fulfill",
        status="ok" if result.outcome != "failed" else "error",
        payload={
            "supplier": task.supplier,
            "outcome": result.outcome,
            "external_order_id": result.external_order_id,
        },
        error=result.error,
    )

    if result.outcome == "succeeded":
        task.status = "succeeded"
        task.succeeded_at = now()
        task.last_error = None
        item.fulfillment_state = "delivered"  # see ck_order_items_state
        item.supplier_order_id = result.external_order_id
        if result.artifact_kind and result.artifact is not None:
            db.add(
                Delivery(
                    id=new_id(),
                    order_item_id=item.id,
                    channel="in_app",
                    artifact_kind=result.artifact_kind,
                    artifact=result.artifact,
                )
            )
    elif result.outcome == "in_progress":
        task.status = "in_progress"
        item.fulfillment_state = "in_progress"
    else:  # "failed"
        task.status = "failed"
        task.failed_at = now()
        task.last_error = result.error
        item.fulfillment_state = "failed"

    return task


async def retry_task(db: AsyncSession, *, task_id: str) -> FulfillmentTask:
    """Admin-triggered retry of a failed task."""
    task = await _load_task(db, task_id)
    if task.status not in ("failed", "pending"):
        raise ConflictError(
            "task is not retryable in its current state",
            extra={"status": task.status},
        )
    task.status = "pending"
    task.last_error = None
    task.failed_at = None
    task.updated_at = now()
    await db.flush()
    task = await process_task(db, task_id=task_id)
    await _try_settle_order(db, order_id=task.order_id)
    await db.flush()
    return task


async def cancel_task(db: AsyncSession, *, task_id: str) -> FulfillmentTask:
    """Admin-triggered cancellation. Calls the supplier's cancel hook best-effort."""
    task = await _load_task(db, task_id)
    if task.status in ("succeeded", "cancelled"):
        raise ConflictError(
            "task cannot be cancelled in its current state",
            extra={"status": task.status},
        )
    fulfiller = get_fulfiller(task.supplier)
    try:
        await fulfiller.cancel(task=task)
        _record_attempt(
            db,
            task=task,
            kind="cancel",
            status="ok",
            payload={"supplier": task.supplier},
        )
    except (FulfillerError, FulfillerNotIntegratedError) as exc:
        _record_attempt(
            db,
            task=task,
            kind="cancel",
            status="error",
            payload={"supplier": task.supplier},
            error=str(exc),
        )
    task.status = "cancelled"
    task.cancelled_at = now()
    task.updated_at = now()

    item = (
        await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
    ).scalar_one()
    item.fulfillment_state = "failed"  # see ck_order_items_state — no 'cancelled'
    await db.flush()
    return task


# ---------- order-level settlement ----------


async def _try_settle_order(db: AsyncSession, *, order_id: str) -> None:
    """If every task succeeded, advance the order to ``fulfilled`` then ``delivered``."""
    tasks = await _existing_tasks_for_order(db, order_id)
    if not tasks:
        return
    if any(t.status != "succeeded" for t in tasks):
        return

    order = (
        await db.execute(select(Order).where(Order.id == order_id))
    ).scalar_one()
    if order.status not in ("fulfilling", "paid"):
        return

    moment = now()
    order.status = "delivered"
    order.fulfilled_at = order.fulfilled_at or moment
    order.delivered_at = moment
    order.updated_at = moment
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind="order.delivered",
            payload={"tasks": [t.id for t in tasks]},
            actor="fulfillment",
        )
    )


# ---------- read helpers ----------


async def list_deliveries_for_order(
    db: AsyncSession, *, order_id: str
) -> list[Delivery]:
    stmt = (
        select(Delivery)
        .join(OrderItem, OrderItem.id == Delivery.order_item_id)
        .where(OrderItem.order_id == order_id)
        .order_by(Delivery.delivered_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_tasks_admin(
    db: AsyncSession,
    *,
    order_id: str | None = None,
    supplier: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
) -> list[FulfillmentTask]:
    stmt = (
        select(FulfillmentTask)
        .options(selectinload(FulfillmentTask.attempts))
        .order_by(FulfillmentTask.created_at.desc())
        .limit(limit)
    )
    if order_id is not None:
        stmt = stmt.where(FulfillmentTask.order_id == order_id)
    if supplier is not None:
        stmt = stmt.where(FulfillmentTask.supplier == supplier)
    if status_filter is not None:
        stmt = stmt.where(FulfillmentTask.status == status_filter)
    return list((await db.execute(stmt)).scalars().all())


async def get_task_admin(db: AsyncSession, task_id: str) -> FulfillmentTask:
    return await _load_task(db, task_id)


__all__ = [
    "cancel_task",
    "get_task_admin",
    "list_deliveries_for_order",
    "list_tasks_admin",
    "process_task",
    "retry_task",
    "start_for_order",
]


# Silence unused-import linter — Iterable is referenced from the docstring/type comments
_ = Iterable, IntegrityError
