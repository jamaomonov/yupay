"""Fulfilment saga (synchronous skeleton).

Drives an order from ``paid`` through ``fulfilling → fulfilled → delivered`` by
creating one :class:`FulfillmentTask` per :class:`OrderItem`, executing each task
in-process against the resolved :class:`Fulfiller`, recording each interaction
in ``fulfillment_attempts``, and persisting the artifact in ``deliveries``.

When the Dramatiq worker lands, ``start_for_order`` writes an outbox row instead
of executing inline; the public API stays the same.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
from collections.abc import Coroutine, Iterable
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
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
from yupay.modules.inventory import service as inv_svc
from yupay.modules.orders.models import Order, OrderEvent, OrderItem
from yupay.modules.sourcing import service as sourcing_svc
from yupay.modules.sourcing.service import Decision

log = get_logger("yupay.fulfillment.service")

INVENTORY_ROUTE = "inventory"
_SUPPLIER_PREFIX = "supplier:"

# Mirrors ``g2b.LOW_BALANCE_ERROR``. Duplicated here (instead of imported)
# to keep the saga independent of any one supplier module — once a
# second adapter ships with the same kind of soft-failure, both will
# write the same sentinel string and the saga will route them
# identically.
_LOW_BALANCE_ERROR = "supplier_low_balance"
# Redis-side dedupe window. Without it a 50-order backlog after a
# balance drop would fan out 50 Telegram messages in the same minute.
# 15 min covers a typical "see the alert, top up the wallet, retry"
# loop without burying ops in repeats.
_LOW_BALANCE_ALERT_DEDUPE_SECONDS = 15 * 60


# ---------- supplier routing ----------


def _route_label(decision: Decision) -> str:
    """Persisted ``fulfillment_tasks.supplier`` value for a routing decision."""
    if decision.primary == "inventory":
        return INVENTORY_ROUTE
    return decision.primary.removeprefix(_SUPPLIER_PREFIX) or decision.primary


def _supplier_slug(route: str) -> str:
    return route.removeprefix(_SUPPLIER_PREFIX) if route.startswith(_SUPPLIER_PREFIX) else route


# ---------- loaders ----------


async def _load_order_with_items(db: AsyncSession, order_id: str) -> Order:
    # Suppliers (notably the mock fulfiller, but real ones too once we wire
    # them) read ``item.sku.product.kind`` to decide whether to mint a
    # voucher code or a top-up receipt — async SA refuses lazy loads, so
    # eager-load the chain right here.
    from yupay.modules.catalog.models import Sku

    stmt = (
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.sku).selectinload(Sku.product),
            selectinload(Order.events),
        )
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


async def _existing_tasks_for_order(db: AsyncSession, order_id: str) -> list[FulfillmentTask]:
    stmt = (
        select(FulfillmentTask)
        .options(selectinload(FulfillmentTask.attempts))
        .where(FulfillmentTask.order_id == order_id)
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------- audit ----------


async def _record_attempt(
    db: AsyncSession,
    *,
    task: FulfillmentTask,
    kind: str,
    status: str,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Append an interaction to the task's audit log, folding repeats.

    The poller asks the supplier for a status once a minute for as long as the
    order stays open, and every answer used to become a row: one production
    task holds 1641, of which 1640 are the identical "still in progress". They
    say nothing the first one does not — except that we were still checking at
    T, which ``last_seen_at``/``repeat_count`` record on the row itself.

    So an attempt identical to the task's most recent one (same kind, status,
    payload and error) updates that row instead of adding another. Anything
    that differs — a new outcome, an error appearing or clearing — starts a new
    row, which is what makes the log a record of what *changed*.

    ``attempts_count`` counts rows, not observations, so it stays in step with
    the log the admin panel renders and stops reporting a well-behaved task as
    having been attempted 1641 times. (`stats.analytics.ops` averages it per
    supplier; polls had pushed that average to 47.6.)
    """
    previous = (
        await db.execute(
            select(FulfillmentAttempt)
            .where(FulfillmentAttempt.task_id == task.id)
            .order_by(FulfillmentAttempt.created_at.desc(), FulfillmentAttempt.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    moment = now()
    if (
        previous is not None
        and previous.kind == kind
        and previous.status == status
        and previous.error == error
        and previous.payload == (payload or {})
    ):
        previous.repeat_count += 1
        previous.last_seen_at = moment
        task.updated_at = moment
        return

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
    task.updated_at = moment

    # Every way fulfilment can go wrong lands here: a supplier call that threw,
    # and a call that succeeded while *reporting* failure (both record
    # ``status="error"``). Alerting from this one place is what makes "any
    # error reaches us" true, rather than a list of call sites someone has to
    # remember to extend.
    if status == "error":
        _dispatch_alert(_alert_fulfillment_error(task, kind=kind, error=error))


# ---------- realtime ----------


async def _publish_status_changed(order: Order) -> None:
    """Nudge the order's owner (if any) over the realtime channel.

    No-op for guest orders (``order.user_id is None``) — that check lives in
    ``publish_order_event`` itself. Imported lazily to avoid pulling the WS
    route stack into every fulfilment import.
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


async def _publish_delivered(order: Order) -> None:
    """Tell the order's owner (if any) the order just reached ``delivered``."""
    from yupay.modules.realtime import api as realtime

    await realtime.publish_order_event(
        order.user_id,
        {
            "type": "order.delivered",
            "orderId": order.id,
            "payload": {"kind": "order", "data": None},
        },
    )


# ---------- core saga ----------


async def start_for_order(
    db: AsyncSession, *, order_id: str, settings: Settings | None = None
) -> list[FulfillmentTask]:
    """Plan and execute fulfilment for a freshly-paid order.

    Creates one task per order item (idempotent — re-running on the same order
    is a no-op because of the ``UNIQUE(order_item_id)`` constraint), drives
    order ``paid → fulfilling``, then — with ``fulfilment_async`` off (the
    default) — processes every task in-process, same as always. With it on,
    tasks are left ``pending`` for the worker and a ``pg_notify`` rides the
    caller's transaction instead.
    """
    order = await _load_order_with_items(db, order_id)
    if order.status not in ("paid", "fulfilling"):
        raise ConflictError(
            "order is not in a fulfilment-ready state",
            extra={"status": order.status},
        )
    # A wallet deposit has no items, so this would create no tasks, still flip
    # the order to ``fulfilling``, and then strand it there — ``_try_settle_order``
    # returns early when there is nothing to settle. A held deposit is resolved
    # by crediting or refunding the customer, not by releasing it to fulfilment;
    # see docs/runbooks/paid-after-expiry.md.
    if order.purpose != "catalog":
        raise ConflictError(
            "a wallet top-up has nothing to fulfil",
            extra={"purpose": order.purpose},
        )

    existing = {t.order_item_id: t for t in await _existing_tasks_for_order(db, order_id)}
    new_tasks: list[FulfillmentTask] = []
    for item in order.items:
        if item.id in existing:
            new_tasks.append(existing[item.id])
            continue
        decision = await sourcing_svc.resolve_for_sku(db, item.sku_id)
        task = FulfillmentTask(
            id=new_id(),
            order_id=order.id,
            order_item_id=item.id,
            supplier=_route_label(decision),
            status="pending",
        )
        db.add(task)
        new_tasks.append(task)

    transitioned_to_fulfilling = False
    if order.status == "paid":
        order.status = "fulfilling"
        order.updated_at = now()
        transitioned_to_fulfilling = True
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
    if transitioned_to_fulfilling:
        await _publish_status_changed(order)

    cfg = settings or get_settings()
    if cfg.fulfilment_async:
        # Planned, not executed: the rows ARE the queue (they just landed in
        # the caller's transaction, atomically with the payment). The NOTIFY
        # rides the same transaction — Postgres delivers it on COMMIT and
        # drops it on ROLLBACK, so a nudge can neither outrun the commit nor
        # survive a rollback. The worker's poll tick covers a nudge lost to
        # a worker restart; nothing here needs to care.
        await db.execute(text("SELECT pg_notify('fulfillment_queue', :oid)"), {"oid": order_id})
    else:
        for task in new_tasks:
            if task.status == "pending":
                await process_task(db, task_id=task.id)

    await _try_settle_order(db, order_id=order_id)
    await db.flush()
    return new_tasks


async def _inventory_fulfill(db: AsyncSession, *, task: FulfillmentTask, item: OrderItem) -> bool:
    """Try to satisfy the task from the warehouse.

    Returns True on success. On ``NoStockError`` returns False — caller decides
    whether to fall back or mark the task failed.
    """
    try:
        issued = await inv_svc.reserve_and_issue(db, sku_id=item.sku_id, order_item_id=item.id)
    except inv_svc.NoStockError as exc:
        await _record_attempt(
            db,
            task=task,
            kind="fulfill",
            status="error",
            payload={"route": INVENTORY_ROUTE, "reason": "no_stock"},
            error=str(exc),
        )
        return False

    task.external_order_id = issued.inventory_code_id
    task.status = "succeeded"
    task.succeeded_at = now()
    task.last_error = None
    item.fulfillment_state = "delivered"
    item.supplier_order_id = issued.inventory_code_id
    db.add(
        Delivery(
            id=new_id(),
            order_item_id=item.id,
            channel="in_app",
            artifact_kind="voucher_code",
            artifact={
                "code": issued.code,
                "inventory_code_id": issued.inventory_code_id,
                "source": INVENTORY_ROUTE,
            },
        )
    )
    await _record_attempt(
        db,
        task=task,
        kind="fulfill",
        status="ok",
        payload={
            "route": INVENTORY_ROUTE,
            "inventory_code_id": issued.inventory_code_id,
        },
    )
    return True


async def process_task(  # noqa: PLR0915 -- linear saga; splitting hurts readability
    db: AsyncSession, *, task_id: str
) -> FulfillmentTask:
    """Run a single task and persist the outcome.

    Routing: if ``task.supplier == 'inventory'`` (set by ``start_for_order`` from
    the sourcing decision), serve from the warehouse. On no-stock we re-consult
    sourcing to decide whether to fall back to a supplier (mode='auto') or fail
    the task (mode='force_inventory').
    """
    task = await _load_task(db, task_id)
    if task.status in ("succeeded", "cancelled"):
        return task

    # Eager-load ``item.sku.product`` — real-supplier fulfillers read
    # ``sku.cost_usdt`` (pre-flight balance check) and ``sku.product.kind``
    # (artifact decision). Async SA raises on lazy attribute access
    # otherwise.
    from yupay.modules.catalog.models import Sku

    item = (
        await db.execute(
            select(OrderItem)
            .options(selectinload(OrderItem.sku).selectinload(Sku.product))
            .where(OrderItem.id == task.order_item_id)
        )
    ).scalar_one()
    order = (await db.execute(select(Order).where(Order.id == task.order_id))).scalar_one()

    task.status = "in_progress"
    task.updated_at = now()

    # ---- inventory route ----
    if task.supplier == INVENTORY_ROUTE:
        if await _inventory_fulfill(db, task=task, item=item):
            return task
        # No stock — check sourcing rule to decide fallback.
        decision = await sourcing_svc.resolve_for_sku(db, item.sku_id)
        if decision.strict or decision.fallback is None:
            task.status = "failed"
            task.failed_at = now()
            task.last_error = "no stock and sourcing rule is strict"
            item.fulfillment_state = "failed"
            return task
        # Switch the route to the supplier fallback for the rest of this attempt.
        task.supplier = _supplier_slug(decision.fallback)
        await _record_attempt(
            db,
            task=task,
            kind="fulfill",
            status="ok",
            payload={"route_switch": task.supplier, "reason": "inventory_no_stock"},
        )

    # ---- supplier route ----
    fulfiller: Fulfiller = get_fulfiller(task.supplier)

    try:
        result: FulfillResult = await fulfiller.fulfill(
            db=db, order=order, item=item, idempotency_key=task.id
        )
    except (FulfillerError, FulfillerNotIntegratedError) as exc:
        await _record_attempt(
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

    await _record_attempt(
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
        # Low-balance is the one "failed" mode we deliberately hide
        # from the customer: the task lands in the admin inbox, but
        # the order item stays ``in_progress`` so the storefront keeps
        # saying "обработка" instead of flipping to an error state.
        # The admin will either top up + retry, or fulfil manually.
        if result.error == _LOW_BALANCE_ERROR:
            item.fulfillment_state = "in_progress"
            _dispatch_alert(_maybe_alert_low_balance(task=task, result=result))
        else:
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


async def bulk_retry_tasks(
    db: AsyncSession, *, task_ids: list[str]
) -> tuple[list[FulfillmentTask], list[tuple[str, str]]]:
    """Best-effort retry for a batch.

    Each task is replayed via :func:`retry_task`; ones that can't be (unknown id,
    wrong status) are returned in the second tuple with a short reason instead of
    aborting the whole batch. Duplicates in ``task_ids`` are deduped, preserving
    first-seen order.
    """
    seen: set[str] = set()
    deduped: list[str] = []
    for tid in task_ids:
        if tid in seen:
            continue
        seen.add(tid)
        deduped.append(tid)

    retried: list[FulfillmentTask] = []
    skipped: list[tuple[str, str]] = []
    for tid in deduped:
        try:
            task = await retry_task(db, task_id=tid)
        except NotFoundError as exc:
            skipped.append((tid, exc.detail))
        except ConflictError as exc:
            status_hint = exc.extra.get("status") if exc.extra else None
            reason = f"not retryable (status={status_hint})" if status_hint else exc.detail
            skipped.append((tid, reason))
        else:
            retried.append(task)
    return retried, skipped


async def _apply_cancel(db: AsyncSession, *, task: FulfillmentTask, reason: str) -> None:
    """Run the supplier cancel hook (best-effort), then flip the task to
    ``cancelled`` and its order item to ``failed``.

    ``ck_order_items_state`` has no ``cancelled`` value, so a cancelled task's
    item lands in ``failed``. Shared by the single-task admin cancel and the
    order/refund cascade — the supplier call is best-effort, a rejection is
    recorded but doesn't block the local state flip (there's nothing to settle
    once the order is gone).
    """
    fulfiller = get_fulfiller(task.supplier)
    try:
        await fulfiller.cancel(db=db, task=task)
        await _record_attempt(
            db,
            task=task,
            kind="cancel",
            status="ok",
            payload={"supplier": task.supplier, "reason": reason},
        )
    except (FulfillerError, FulfillerNotIntegratedError) as exc:
        await _record_attempt(
            db,
            task=task,
            kind="cancel",
            status="error",
            payload={"supplier": task.supplier, "reason": reason},
            error=str(exc),
        )
    moment = now()
    task.status = "cancelled"
    task.cancelled_at = moment
    task.updated_at = moment
    item = (
        await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
    ).scalar_one()
    item.fulfillment_state = "failed"  # see ck_order_items_state — no 'cancelled'


async def cancel_task(db: AsyncSession, *, task_id: str) -> FulfillmentTask:
    """Admin-triggered cancellation of a single task. Calls the supplier's
    cancel hook best-effort. Rejects a task that already terminated
    (``succeeded`` / ``cancelled``)."""
    task = await _load_task(db, task_id)
    if task.status in ("succeeded", "cancelled"):
        raise ConflictError(
            "task cannot be cancelled in its current state",
            extra={"status": task.status},
        )
    await _apply_cancel(db, task=task, reason="admin_cancel")
    await db.flush()
    return task


async def cancel_open_tasks_for_order(
    db: AsyncSession, *, order_id: str, reason: str
) -> list[FulfillmentTask]:
    """Cancel every still-open fulfilment task for a terminating order.

    Called when the order is cancelled or its payment refunded (see
    ``orders.service.cancel_order_admin`` and ``payments.service.refund_admin``)
    so the fulfilment saga doesn't keep trying to deliver — or leave a stuck
    ``failed`` task — for an order the customer no longer owns.

    Tasks that already ``succeeded`` are left untouched: the customer already
    received the goods, and a money refund does not retract a delivered code.
    Already-``cancelled`` tasks are skipped, so this is idempotent.
    """
    cancelled: list[FulfillmentTask] = []
    for task in await _existing_tasks_for_order(db, order_id):
        if task.status in ("succeeded", "cancelled"):
            continue
        await _apply_cancel(db, task=task, reason=reason)
        cancelled.append(task)
    if cancelled:
        await db.flush()
    return cancelled


# ---------- alert dispatch ----------

#: Strong references to in-flight alert tasks. Without them the event loop is
#: free to garbage-collect a pending task mid-send, and the alert vanishes.
_ALERT_TASKS: set[asyncio.Task[None]] = set()


def _dispatch_alert(coro: Coroutine[Any, Any, None]) -> None:
    """Start an alert without making the caller wait for Telegram.

    Alerts fire from inside the saga, mid-transaction. Awaiting them there put
    an outbound HTTP round trip inside a database transaction — latency on the
    fulfilment path and a transaction held open across a third party we do not
    control (AGENTS.md §10). The alert still leaves immediately; only the
    waiting is gone.

    Outside a running loop (a sync script, some test harnesses) there is
    nothing to schedule on, so the coroutine is closed rather than left as an
    un-awaited warning.
    """
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        coro.close()
        return
    _ALERT_TASKS.add(task)
    task.add_done_callback(_ALERT_TASKS.discard)


# ---------- error alerting ----------

#: How long the same error on the same task stays quiet after the first alert.
#: Consecutive identical failures already collapse into one attempt row
#: (see ``_record_attempt``) and never reach here twice, so this covers the
#: flapping case — error, recovery, same error again — and duplicate delivery
#: from a second worker. An hour is long enough that a task failing every
#: minute costs one message, short enough that an unresolved incident says so
#: again within a shift.
_ERROR_ALERT_DEDUPE_SECONDS = 60 * 60


async def _alert_fulfillment_error(
    task: FulfillmentTask,
    *,
    kind: str,
    error: str | None,
) -> None:
    """Tell ops, immediately, that a fulfilment step failed.

    Never raises and never blocks the saga: an alerting outage must not be
    able to fail an order that is otherwise recoverable, so every failure here
    is swallowed and logged.

    The message deliberately carries no ``fulfillment_data`` — that is where
    the customer's Steam login and player ids live (§9). Supplier error text
    is included because it is the one thing that says *what to do*, truncated
    so a stack trace cannot turn into a wall of chat.
    """
    from yupay.modules.notifications import api as notifications

    detail = (error or "").strip() or "без текста ошибки"
    signature = hashlib.sha1(detail.encode("utf-8")).hexdigest()[:12]  # noqa: S324 -- dedupe key, not a secret
    key = f"alert:fulfill_error:{task.id}:{kind}:{signature}"
    try:
        if await _set_redis_dedupe(key, ttl_seconds=_ERROR_ALERT_DEDUPE_SECONDS):
            return
        text = (
            "<b>🛑 Ошибка фулфилмента</b>\n"
            f"Шаг: <code>{html.escape(kind)}</code> · "
            f"Поставщик: <code>{html.escape(task.supplier or '?')}</code>\n"
            f"Заказ: <code>{task.order_id}</code>\n"
            f"Задача: <code>{task.id}</code>\n"
            f"<pre>{html.escape(detail[:300])}</pre>"
        )
        await notifications.send_admin_alert(text, kind="fulfillment_error")
    except Exception as exc:  # noqa: BLE001 -- alerting must never break a sale
        log.warning(
            "fulfillment.error_alert_failed",
            task_id=task.id,
            kind=kind,
            error=str(exc)[:200],
        )


# ---------- low-balance alerting ----------


async def _maybe_alert_low_balance(
    *,
    task: FulfillmentTask,
    result: FulfillResult,
) -> None:
    """Send an ops Telegram alert when a supplier rejects an order for
    lack of funds — but only once per supplier per dedupe window.

    Dedupe lives in Redis so the lock survives across uvicorn workers
    and a process restart. A Redis outage degrades to "alert every time"
    rather than "alert never"; we'd rather over-notify than miss the
    incident.
    """
    from yupay.modules.notifications import api as notifications

    extra = result.extra_metadata or {}
    supplier = str(extra.get("supplier") or task.supplier or "unknown")
    key = f"alert:low_balance:{supplier}"

    if await _set_redis_dedupe(key, ttl_seconds=_LOW_BALANCE_ALERT_DEDUPE_SECONDS):
        # Another worker already alerted for this supplier within the
        # window — silently drop this one.
        return

    current = extra.get("current_balance") or "?"
    required = extra.get("required") or "?"
    # supplier/ext_id/variant can echo back supplier- or admin-entered free text
    # (mapping fields) — escape before splicing into a parse_mode:HTML message.
    ext_id = html.escape(str(extra.get("external_product_id") or "?"))
    variant = str(extra.get("external_variant_id") or "")
    variant_line = f"\nНоминал: <code>{html.escape(variant)}</code>" if variant else ""
    text = (
        "<b>⚠️ Низкий баланс поставщика</b>\n"
        f"Поставщик: <code>{html.escape(supplier)}</code>\n"
        f"Продукт: <code>{ext_id}</code>{variant_line}\n"
        f"Баланс: <b>${current}</b> · Нужно: <b>${required}</b>\n"
        f"<i>Задача: {task.id[:8]}… · клиент видит «в обработке».</i>\n"
        f"Пополни счёт и нажми «Повторить» в Fulfilment Inbox."
    )
    await notifications.send_admin_alert(text, kind="supplier_low_balance")


async def _set_redis_dedupe(key: str, *, ttl_seconds: int) -> bool:
    """Return ``True`` if the key was already set (i.e. a previous alert
    is still within the dedupe window).

    Uses SET NX so the check + set is atomic. Swallows Redis errors —
    a dead Redis must not block the saga, and degrading to "alert every
    time" is the right failure mode for an alert dedupe.
    """
    try:
        import redis.asyncio as redis

        client = redis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            existed = not await client.set(key, "1", ex=ttl_seconds, nx=True)
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001 -- Redis outage degrades to "alert each time"
        log.warning("alerts.dedupe.redis_unavailable", error=str(exc), key=key)
        return False
    return existed


# ---------- async-supplier reconciliation (webhook & polling) ----------


async def process_webhook_update(
    db: AsyncSession,
    *,
    task_id: str,
) -> FulfillmentTask:
    """Reconcile a task with the supplier after an out-of-band signal.

    Called from the supplier-specific webhook route and from the polling
    actor. We **never** trust the webhook body — instead we ask the
    fulfiller's ``check_status`` for the authoritative view and apply the
    same state transitions the synchronous saga would have done.
    """
    task = await _load_task(db, task_id)
    if task.status in ("succeeded", "cancelled"):
        # Nothing to do — terminal-but-good.
        return task
    if task.status == "failed":
        # Idempotent: a webhook that arrives after manual /fail is a no-op.
        return task

    fulfiller = get_fulfiller(task.supplier)
    try:
        status = await fulfiller.check_status(db=db, task=task)
    except (FulfillerError, FulfillerNotIntegratedError) as exc:
        await _record_attempt(
            db,
            task=task,
            kind="status_check",
            status="error",
            payload={"supplier": task.supplier},
            error=str(exc),
        )
        log.warning(
            "fulfillment.check_status.failed",
            task_id=task.id,
            supplier=task.supplier,
            error=str(exc),
        )
        return task

    item = (
        await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
    ).scalar_one()

    await _record_attempt(
        db,
        task=task,
        kind="status_check",
        status="ok" if status.outcome != "failed" else "error",
        payload={"supplier": task.supplier, "outcome": status.outcome},
        error=status.error,
    )

    # Persist any structured flags the supplier reported (needs_reconciliation,
    # supplier_refunded, give_amount_shortfall_units) so the admin inbox can
    # filter on them, not just grep last_error. Same merge the fulfill() path
    # does with FulfillResult.extra_metadata.
    if status.extra_metadata:
        task.extra_metadata = {**(task.extra_metadata or {}), **status.extra_metadata}

    if status.outcome == "succeeded":
        task.status = "succeeded"
        task.succeeded_at = now()
        task.last_error = None
        item.fulfillment_state = "delivered"
        if status.artifact_kind and status.artifact is not None:
            # Deliveries are unique on order_item_id — guard against a
            # double-fire by checking first instead of letting the
            # IntegrityError bubble up and abort the session.
            existing = (
                await db.execute(select(Delivery).where(Delivery.order_item_id == item.id))
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    Delivery(
                        id=new_id(),
                        order_item_id=item.id,
                        channel="in_app",
                        artifact_kind=status.artifact_kind,
                        artifact=status.artifact,
                    )
                )
    elif status.outcome == "failed":
        task.status = "failed"
        task.failed_at = now()
        task.last_error = status.error or "supplier reported failure"
        item.fulfillment_state = "failed"
    # ``in_progress`` — leave the task untouched; the next poll / webhook
    # will fire again.

    await _try_settle_order(db, order_id=task.order_id)
    await db.flush()
    return task


# ---------- manual fulfilment (admin-driven) ----------


_VALID_ARTIFACT_KINDS = frozenset({"voucher_code", "topup_receipt", "license_key"})
_VALID_DELIVERY_CHANNELS = frozenset({"in_app", "email", "telegram"})


async def complete_manual_task(
    db: AsyncSession,
    *,
    task_id: str,
    artifact_kind: str,
    artifact: dict[str, Any],
    channel: str | None,
    admin_note: str | None,
    admin_id: str,
    proof_url: str | None = None,
    force: bool = False,
) -> FulfillmentTask:
    """Admin marks a task as completed by hand.

    Default behaviour is unchanged: only ``supplier="manual"`` tasks in
    ``in_progress`` can be finalised here, so real supplier tasks can't
    drift away from their upstream's idea of state.

    ``force=True`` is the supplier-side escape hatch: an admin uses it
    when a real supplier rejected the order (typically
    ``supplier_low_balance`` after the operator topped up off-platform
    and delivered the code manually). In that mode we accept any
    supplier and any ``failed | in_progress`` status, and tag the
    audit row + ``extra_metadata.force_complete=True`` so the action is
    distinguishable in the audit feed.
    """
    task = await _load_task(db, task_id)
    if not force:
        if task.supplier != "manual":
            raise ConflictError(
                "task is not a manual task",
                extra={"supplier": task.supplier},
            )
        if task.status != "in_progress":
            raise ConflictError(
                "manual task cannot be completed in its current state",
                extra={"status": task.status},
            )
    elif task.status not in ("in_progress", "failed"):
        raise ConflictError(
            "task cannot be force-completed in its current state",
            extra={"status": task.status},
        )
    if artifact_kind not in _VALID_ARTIFACT_KINDS:
        from yupay.core.errors import ValidationError

        raise ValidationError(
            f"unsupported artifact_kind: {artifact_kind!r}",
            extra={"allowed": sorted(_VALID_ARTIFACT_KINDS)},
        )
    resolved_channel = channel or "in_app"
    if resolved_channel not in _VALID_DELIVERY_CHANNELS:
        from yupay.core.errors import ValidationError

        raise ValidationError(
            f"unsupported delivery channel: {resolved_channel!r}",
            extra={"allowed": sorted(_VALID_DELIVERY_CHANNELS)},
        )
    if not artifact:
        from yupay.core.errors import ValidationError

        raise ValidationError("artifact must contain at least one key")

    item = (
        await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
    ).scalar_one()
    # Captured before the savepoint: its rollback expires ORM instances, and
    # touching ``item.id`` in the except-branch would trigger a lazy refresh.
    order_item_id = item.id

    try:
        # UNIQUE(order_item_id) on ``deliveries`` is the DB-level idempotency
        # guarantee — even if two admins race the in-process status guard,
        # only one row lands. The SAVEPOINT opens BEFORE the Delivery is
        # added: ``begin_nested()`` autoflushes pending state first, so a
        # later savepoint would let the failing INSERT poison the outer
        # transaction instead of rolling back just this block.
        async with db.begin_nested():
            db.add(
                Delivery(
                    id=new_id(),
                    order_item_id=item.id,
                    channel=resolved_channel,
                    artifact_kind=artifact_kind,
                    artifact=artifact,
                )
            )
            moment = now()
            task.status = "succeeded"
            task.succeeded_at = moment
            task.last_error = None
            task.completed_by = admin_id
            task.admin_note = admin_note
            task.updated_at = moment
            new_meta: dict[str, Any] = {}
            if proof_url is not None and proof_url.strip():
                new_meta["proof_url"] = proof_url.strip()
            if force:
                # Audit marker — the admin overrode a real-supplier task
                # instead of completing a regular manual one. Surfaced in the
                # activity feed so it's clear this delivery never passed
                # through the supplier's fulfilment pipeline.
                new_meta["force_complete"] = True
            if new_meta:
                task.extra_metadata = {**(task.extra_metadata or {}), **new_meta}
            item.fulfillment_state = "delivered"
            await _record_attempt(
                db,
                task=task,
                kind="fulfill",
                status="ok",
                payload={
                    "manual": True,
                    "admin_id": admin_id,
                    **({"force_complete": True} if force else {}),
                },
            )
            await db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "item already has a delivery",
            extra={"order_item_id": order_item_id},
        ) from exc
    await _try_settle_order(db, order_id=task.order_id)
    await db.flush()
    return task


async def fail_manual_task(
    db: AsyncSession,
    *,
    task_id: str,
    reason: str,
    admin_note: str | None,
    admin_id: str,
) -> FulfillmentTask:
    """Admin rejects a manual task (e.g. account suspended, no stock, …).

    Marks the task as ``failed`` with ``reason`` as ``last_error``. The
    order stays in ``fulfilling``; refunds are issued separately through
    ``/admin/payments/{id}/refund`` so the admin keeps explicit control
    over the money side.
    """
    task = await _load_task(db, task_id)
    if task.supplier != "manual":
        raise ConflictError(
            "task is not a manual task",
            extra={"supplier": task.supplier},
        )
    if task.status != "in_progress":
        raise ConflictError(
            "manual task cannot be failed in its current state",
            extra={"status": task.status},
        )
    reason_clean = reason.strip()
    if not reason_clean:
        from yupay.core.errors import ValidationError

        raise ValidationError("reason is required to reject a manual task")

    item = (
        await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
    ).scalar_one()

    moment = now()
    task.status = "failed"
    task.failed_at = moment
    task.last_error = reason_clean
    task.completed_by = admin_id
    task.admin_note = admin_note
    task.updated_at = moment
    item.fulfillment_state = "failed"
    await _record_attempt(
        db,
        task=task,
        kind="fulfill",
        status="error",
        payload={"manual": True, "admin_id": admin_id},
        error=reason_clean,
    )
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

    order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one()
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

    # Immediate realtime push (in-transaction, not after-commit): the client
    # treats it as a nudge and re-fetches the order, so a rare rollback after
    # this point self-corrects on that refetch.
    await _publish_delivered(order)

    # Telegram push — fire-and-forget *after commit* so a slow / down
    # Telegram never blocks the saga AND the notification's own session can
    # see the persisted delivery rows. Notifications swallow their own
    # errors.
    from yupay.modules.notifications import api as notifications

    order_id = order.id
    notifications.schedule_after_commit(
        db,
        lambda: notifications.notify_order_delivered(order_id),
    )


# ---------- read helpers ----------


async def list_deliveries_for_order(db: AsyncSession, *, order_id: str) -> list[Delivery]:
    stmt = (
        select(Delivery)
        .join(OrderItem, OrderItem.id == Delivery.order_item_id)
        .where(OrderItem.order_id == order_id)
        .order_by(Delivery.delivered_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_deliveries_for_order_admin(
    db: AsyncSession, *, order_id: str, admin_id: str
) -> list[Delivery]:
    """Delivered artifacts for an order, for support — and an audit trail.

    Support cannot answer "the code doesn't work" without seeing the code that
    was actually issued, but a voucher code is a bearer instrument: whoever
    reads it can redeem it. So every read is recorded on the order timeline
    with the acting admin, making "who looked at this customer's codes" a
    question the audit feed can answer.

    Unlike the customer-facing route this returns the artifact **unfiltered** —
    the internal fields (upstream order id, source, inventory row) are exactly
    what an operator needs when reconciling with a supplier.
    """
    deliveries = await list_deliveries_for_order(db, order_id=order_id)
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order_id,
            kind="admin.deliveries_viewed",
            payload={"count": len(deliveries)},
            actor=f"admin:{admin_id}",
        )
    )
    await db.flush()
    return deliveries


async def list_tasks_admin(
    db: AsyncSession,
    *,
    order_id: str | None = None,
    supplier: str | None = None,
    status_filter: str | None = None,
    order: str = "newest",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[FulfillmentTask], int]:
    """Paged admin listing. Returns ``(rows, total_matching_filter)``.

    ``order`` picks the created-at direction: ``"newest"`` (default) for the
    browse view, where recent activity belongs on page one; ``"oldest"`` for
    the operator work queues (stuck / failed / manual retry), where the
    longest-waiting task is the most urgent. The distinction matters under a
    backlog larger than ``limit``: those queues fetch a capped window and sort
    client-side, so a ``"newest"`` order would silently drop the oldest — and
    most overdue — tasks off the end. ``created_at`` alone is not unique for
    tasks created in the same bulk operation, so ``id`` is the deterministic
    tiebreak in both directions (stable pagination, no row seen twice or
    skipped across pages)."""
    ascending = order == "oldest"
    created_order = (
        FulfillmentTask.created_at.asc() if ascending else FulfillmentTask.created_at.desc()
    )
    id_order = FulfillmentTask.id.asc() if ascending else FulfillmentTask.id.desc()
    # Attempts are deliberately NOT eager-loaded: the list renders a count,
    # never the log, and loading them shipped every attempt of every row.
    # One production task polls its supplier's status once a minute while the
    # order stays open — 1641 rows, 218 kB — so a single page of 50 carried a
    # quarter of a megabyte nothing on screen used. The detail panel pages
    # through `list_attempts_admin(task_id=...)` instead.
    base = select(FulfillmentTask)
    count_stmt = select(func.count()).select_from(FulfillmentTask)
    if order_id is not None:
        base = base.where(FulfillmentTask.order_id == order_id)
        count_stmt = count_stmt.where(FulfillmentTask.order_id == order_id)
    if supplier is not None:
        base = base.where(FulfillmentTask.supplier == supplier)
        count_stmt = count_stmt.where(FulfillmentTask.supplier == supplier)
    if status_filter is not None:
        base = base.where(FulfillmentTask.status == status_filter)
        count_stmt = count_stmt.where(FulfillmentTask.status == status_filter)
    rows = list(
        (await db.execute(base.order_by(created_order, id_order).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    return rows, total


async def get_task_admin(db: AsyncSession, task_id: str) -> FulfillmentTask:
    return await _load_task(db, task_id)


async def list_attempts_admin(
    db: AsyncSession,
    *,
    task_id: str | None = None,
    supplier: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[FulfillmentAttempt, str]], int]:
    """Paged admin listing of supplier interaction attempts.

    Returns rows joined with the parent task's supplier slug so the admin
    UI can render "G2B attempts" without a second query per row.

    ``task_id`` narrows the feed to one task's log. That is what lets the
    inbox's detail panel page through attempts instead of receiving every
    one of them at once: a single slow supplier order polls its status once
    a minute for as long as it stays open, and one such task in production
    has 1641 rows behind it.
    """
    base = (
        select(FulfillmentAttempt, FulfillmentTask.supplier)
        .join(FulfillmentTask, FulfillmentTask.id == FulfillmentAttempt.task_id)
        .order_by(FulfillmentAttempt.created_at.desc())
    )
    count_stmt = (
        select(func.count())
        .select_from(FulfillmentAttempt)
        .join(FulfillmentTask, FulfillmentTask.id == FulfillmentAttempt.task_id)
    )
    if task_id is not None:
        base = base.where(FulfillmentAttempt.task_id == task_id)
        count_stmt = count_stmt.where(FulfillmentAttempt.task_id == task_id)
    if supplier is not None:
        base = base.where(FulfillmentTask.supplier == supplier)
        count_stmt = count_stmt.where(FulfillmentTask.supplier == supplier)
    if status_filter is not None:
        base = base.where(FulfillmentAttempt.status == status_filter)
        count_stmt = count_stmt.where(FulfillmentAttempt.status == status_filter)
    rows = list((await db.execute(base.limit(limit).offset(offset))).all())
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    return [(r[0], r[1]) for r in rows], total


__all__ = [
    "bulk_retry_tasks",
    "cancel_open_tasks_for_order",
    "cancel_task",
    "complete_manual_task",
    "fail_manual_task",
    "get_task_admin",
    "list_attempts_admin",
    "list_deliveries_for_order",
    "list_tasks_admin",
    "process_task",
    "process_webhook_update",
    "retry_task",
    "start_for_order",
]


# Silence unused-import linter — Iterable is referenced from the docstring/type comments
_ = Iterable, IntegrityError
