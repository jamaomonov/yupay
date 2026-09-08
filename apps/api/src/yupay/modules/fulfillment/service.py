"""Fulfilment saga (synchronous skeleton).

Drives an order from ``paid`` through ``fulfilling → fulfilled → delivered`` by
creating one :class:`FulfillmentTask` per :class:`OrderItem`, executing each task
in-process against the resolved :class:`Fulfiller`, recording each interaction
in ``fulfillment_attempts``, and persisting the artifact in ``deliveries``.

With ``fulfilment_async`` on, ``start_for_order`` leaves tasks ``pending`` and
fires ``pg_notify('fulfillment_queue', ...)`` on commit instead of executing
inline; ``apps/worker`` drains them via :func:`drain_pending_tasks`. The public
API stays the same either way (ADR-0064).
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
    MoneyOutcome,
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

#: Where a task records what became of our money when it failed. It lives in
#: ``extra_metadata`` rather than a column because that is where every other
#: structured fact about a task already lives, and because nothing queries it
#: yet — M3b Task 3 reads it at the moment the failure happens, on the row it
#: has in hand. Read it with :func:`money_outcome_of`, never by key.
MONEY_OUTCOME_KEY = "money_outcome"

#: Our own warehouse running dry. No supplier is involved in an inventory
#: route at all, so nothing external was ever charged — the cleanest
#: :attr:`MoneyOutcome.RETURNED` in the codebase, and the one case where an
#: automatic refund is unambiguously right.
INVENTORY_FAILURE_MONEY_OUTCOME = MoneyOutcome.RETURNED

#: How much a money outcome commits us to, lowest first. ``record_money_outcome``
#: never moves a task down this ladder: knowledge about our own money only ever
#: accumulates. ``RETURNED`` is the bottom because it is the one value that
#: unlocks an automatic refund, so promoting to it is the expensive mistake;
#: ``SPENT`` is the top because "we know it is gone" is a positive finding that
#: a later "we cannot tell" must not erase — the very blur
#: :class:`MoneyOutcome`'s docstring forbids.
_CONFIDENCE: dict[MoneyOutcome, int] = {
    MoneyOutcome.RETURNED: 0,
    MoneyOutcome.UNKNOWN: 1,
    MoneyOutcome.SPENT: 2,
}

#: A task that crashed on an exception nobody wrapped, or one an admin
#: rejected by hand. Neither can say what happened upstream: the first died
#: mid-saga, and the second is a human who bought (or did not buy) the goods
#: somewhere this code cannot see.
_NOBODY_CAN_SAY = MoneyOutcome.UNKNOWN


def record_money_outcome(task: FulfillmentTask, outcome: MoneyOutcome) -> None:
    """Persist what became of our money on a task that has just failed.

    **A task never moves down :data:`_CONFIDENCE`.** The rung that matters is
    the bottom one: every ``RETURNED`` an adapter can produce is a fact about
    *one attempt* —
    "the supplier refunded this order", "this create never reached the call
    that pays". A task outlives its attempts: an admin Retry re-runs it, and
    the retry knows nothing about what the attempt before it spent. Without
    this rule the sequence is a real money loss, and needs no supplier
    misbehaviour to reach:

    1. ``pay`` is charged and *then* returns HTTP 500 → ``UNKNOWN``, correctly.
    2. An admin clicks Retry — the ordinary response to that failure.
    3. The replay trips a transient outage before it creates anything →
       ``RETURNED``, also correctly, *for that attempt*.
    4. M3b refunds the deposit for goods we have already paid for.

    So once any attempt has left money unaccounted for, no later attempt may
    declare the task's money whole. Upward stays open: a ``RETURNED`` task that
    is retried and then loses money records that, because it is new knowledge
    rather than an older attempt's absence of it. ``SPENT`` is likewise never
    downgraded to ``UNKNOWN`` — a retry whose call fails ambiguously would
    otherwise turn "waxpeer kept our money" into "we cannot tell" in the admin
    inbox. Task 3 treats those two the same, but a human does not.

    There is deliberately **no way to lower a recorded outcome**, here or
    through ``retry_task`` / ``complete_manual_task``. That is safe while only
    a terminal supplier verdict writes one, and it cuts both ways:

    - a caller that starts recording on *transient* errors would make every
      outage a permanent ``UNKNOWN`` on an otherwise fine task;
    - and ``SPENT`` is already unrecoverable **today**. Waxpeer writes it for an
      ``error`` top-up, the runbook's answer is "chase the money", and an
      operator who chases it successfully has no way to record that we are whole
      again — the task reads "money gone" forever and M3b will never refund that
      merchant automatically.

    Either direction needs an operator re-grade path. Neither has one yet.

    The value is merged onto ``extra_metadata`` rather than assigned, so the
    supplier flags the adapters wrote — ``supplier_refunded``,
    ``needs_reconciliation`` and the rest — survive alongside it. Those keys
    stay the admin inbox's and the runbooks' spelling of the same idea; this
    one is the typed source of truth M3b acts on.

    Args:
        task: The task, already marked ``failed``.
        outcome: What became of the money on the attempt that just ended.
    """
    standing = _standing_outcome(task)
    if standing is not None and _CONFIDENCE[outcome] < _CONFIDENCE[standing]:
        log.info(
            "fulfillment.money_outcome.kept",
            task_id=task.id,
            supplier=task.supplier,
            standing=standing.value,
            refused=outcome.value,
        )
        return
    task.extra_metadata = {**(task.extra_metadata or {}), MONEY_OUTCOME_KEY: outcome.value}


def _standing_outcome(task: FulfillmentTask) -> MoneyOutcome | None:
    """The value already on the task, for the ladder — **failing closed**.

    ``money_outcome_of`` reads an unrecognised string as "nothing recorded",
    which is right for a reader but wrong for the guard: it would let a later
    ``RETURNED`` overwrite a value this build merely cannot parse. The one
    re-grade available today is a hand DB edit (see
    :func:`record_money_outcome`), and the enum's values are lowercase, so an
    operator typing ``'UNKNOWN'`` would silently disarm the invariant on that
    task — on the exact rows a human is already worried about.

    A present-but-unreadable value therefore counts as
    :attr:`MoneyOutcome.UNKNOWN`: high enough to block a promotion, low enough
    that real knowledge still lands on top of it.
    """
    standing = money_outcome_of(task)
    if standing is None and (task.extra_metadata or {}).get(MONEY_OUTCOME_KEY) is not None:
        return MoneyOutcome.UNKNOWN
    return standing


def _record_or_warn(
    task: FulfillmentTask, outcome: MoneyOutcome | None, *, discovered: str
) -> None:
    """Record a terminal failure's money outcome, or say out loud that it has none.

    Never raising is the right *behaviour* — a saga must not die because an
    adapter forgot — but swallowing it silently would make the totality
    property unenforced at runtime, so a hole the AST guard cannot see (an
    adapter's intermediate type, a value threaded through a helper) would
    produce no signal at all. M3b Task 3 is about to start acting on this
    field's absence, so absence gets a log line an alert can find.

    The low-balance stall never reaches here: it returns earlier, without an
    outcome and legitimately so.

    Args:
        task: The task, already marked ``failed``.
        outcome: What the adapter said, or ``None`` if it said nothing.
        discovered: Which path found the failure, for the log line.
    """
    if outcome is None:
        log.warning(
            "fulfillment.money_outcome.missing",
            task_id=task.id,
            supplier=task.supplier,
            discovered=discovered,
        )
        return
    record_money_outcome(task, outcome)


def money_outcome_of(task: FulfillmentTask) -> MoneyOutcome | None:
    """What this task's last terminal failure recorded about our money.

    **It outlives that failure.** ``retry_task`` does not clear it and no
    success path removes it, so a task that failed and then succeeded on a
    retry still answers — deliberately, because it is the only trace that an
    earlier attempt may have spent money the successful one did not account
    for, and because :func:`record_money_outcome` needs it to refuse a replay's
    false "we still have the money". A caller asking "what happened to *this*
    order" must therefore pair it with ``task.status == "failed"``; a caller
    asking "is there money unaccounted for on this task" must not.

    ``None`` covers three rows and deliberately does not distinguish them: one
    that has never failed, one that failed before this field existed, and one
    carrying a value this build does not know. The last is why this is a lookup
    rather than a cast — a row written by another deploy must not crash a saga,
    and "we do not know" is already one of the three answers a caller handles.
    """
    raw = (task.extra_metadata or {}).get(MONEY_OUTCOME_KEY)
    return next((m for m in MoneyOutcome if m.value == raw), None)


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


async def _load_task(
    db: AsyncSession, task_id: str, *, for_update: bool = False
) -> FulfillmentTask:
    """Load one task, optionally under a row lock.

    ``for_update=True`` is for the *mutating* callers (admin retry/cancel, and
    the poll/webhook reconciler, which read-modify-writes ``extra_metadata``).
    Without it they read a snapshot taken before the consumer's claim, decide
    on that stale status, and then queue behind the consumer's row lock only
    to overwrite what it just committed — an admin cancel landing on top of a
    committed ``succeeded`` is a refund issued for goods that were delivered.
    ``populate_existing`` is not optional here: a lock whose row is then
    served from the session's identity map (with the attributes it had before
    the lock was granted) proves nothing. Read-only callers stay unlocked —
    an admin list must never wait on a supplier call.
    """
    stmt = (
        select(FulfillmentTask)
        .options(selectinload(FulfillmentTask.attempts))
        .where(FulfillmentTask.id == task_id)
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise NotFoundError("fulfilment task not found")
    return task


async def _existing_tasks_for_order(
    db: AsyncSession, order_id: str, *, for_update: bool = False
) -> list[FulfillmentTask]:
    """Load an order's tasks, optionally under row locks. See :func:`_load_task`.

    The ``created_at, id`` ordering is what keeps the locking variant
    deadlock-free against the drain loop: both take this order's rows in
    ``created_at`` order (``drain_pending_tasks``' claim query orders the same
    way), so two sessions can queue but never wait on each other in a cycle.
    """
    stmt = (
        select(FulfillmentTask)
        .options(selectinload(FulfillmentTask.attempts))
        .where(FulfillmentTask.order_id == order_id)
        .order_by(FulfillmentTask.created_at, FulfillmentTask.id)
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
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


async def _publish_status_changed(
    db: AsyncSession, order: Order, *, publish_realtime: bool = True
) -> None:
    """Route a status change through the orders module's one seam.

    This used to be a verbatim copy of the realtime nudge — one of three. The
    nudge, and the merchant webhook beside it, now live in
    ``orders.service.on_order_status_changed``; the local name is kept so the
    call sites read as they always did. ``publish_realtime=False`` is for the
    settle path, which emits ``order.delivered`` instead and must not start
    sending a connected storefront a second event as well.

    Imported lazily for the reason ``orders.service`` imports *this* module
    lazily: the two reach into each other and a module-level import would
    close the cycle.
    """
    from yupay.modules.orders import service as orders_svc

    await orders_svc.on_order_status_changed(db, order, publish_realtime=publish_realtime)


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
        await _publish_status_changed(db, order)

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


async def process_task(db: AsyncSession, *, task_id: str) -> FulfillmentTask:
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
            record_money_outcome(task, INVENTORY_FAILURE_MONEY_OUTCOME)
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
        # An adapter that raises has ended the order as terminally as one that
        # returns ``failed``, and answers the same question at the raise site.
        record_money_outcome(task, exc.money_outcome)
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
        _apply_failure(task=task, item=item, result=result)

    return task


def _apply_failure(*, task: FulfillmentTask, item: OrderItem, result: FulfillResult) -> None:
    """Land a ``failed`` supplier result on the task and its order item.

    Low-balance is the one "failed" mode we deliberately hide from the
    customer: the task lands in the admin inbox, but the order item stays
    ``in_progress`` so the storefront keeps saying "обработка" instead of
    flipping to an error state. The admin will either top up + retry, or
    fulfil manually. It is also the one failure with **no** money outcome to
    record — nothing has finished happening to the money yet (M3b Task 4 owns
    making that stall visible).
    """
    task.status = "failed"
    task.failed_at = now()
    task.last_error = result.error

    if result.error == _LOW_BALANCE_ERROR:
        item.fulfillment_state = "in_progress"
        _dispatch_alert(_maybe_alert_low_balance(task=task, result=result))
        return

    item.fulfillment_state = "failed"
    _record_or_warn(task, result.money_outcome, discovered="fulfill")


#: Cap for a crashed task's stored error. Long enough to keep a stack-less
#: message useful in the admin UI, short enough that a driver that dumps a
#: whole statement can't fill the column (or a log line) with it.
_CRASH_DETAIL_MAX = 500


def _crash_detail(exc: BaseException) -> str:
    """One-line, bounded description of an unexpected task crash.

    Leads with the type because a bare ``str(exc)`` from an unexpected
    exception is often empty or meaningless on its own.

    First line only, then a length cap — both are PII bounds, not cosmetics
    (AGENTS.md §9). This string lands in ``fulfillment_tasks.last_error``,
    which the admin UI shows and the crash log line echoes, and the most
    likely unexpected exception on this path is a SQLAlchemy
    ``IntegrityError``, which stringifies as the driver message, then a
    ``DETAIL: Key (email)=(...)`` line, then the full statement and its
    **bound parameters** — customer email, delivery address. Every one of
    those sits on its own line after the first, so taking the first line
    drops them; the cap bounds whatever a future driver puts on line one.
    """
    lines = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {lines[0] if lines else ''}"[:_CRASH_DETAIL_MAX]


async def drain_pending_tasks(db: AsyncSession, *, limit: int = 20) -> int:
    """Claim and run pending fulfilment tasks. The worker's whole job.

    ``FOR UPDATE SKIP LOCKED`` is the entire concurrency story: duplicate
    notifications, a second worker replica, a poll tick racing a NOTIFY —
    whoever locks a row first runs it, everyone else skips. A crashed
    consumer's locks die with its connection and the next tick reclaims.

    Claims ``status='pending'`` only. ``failed`` stays a human decision
    (admin retry), exactly as in the synchronous mode — the async migration
    changes where work runs, never what counts as runnable.

    Each claimed task runs inside its own ``SAVEPOINT``. ``process_task``
    already turns every *expected* supplier failure (``FulfillerError`` /
    ``FulfillerNotIntegratedError``) into a handled ``failed`` task and
    returns normally — the savepoint is for the unexpected kind: a raw
    ``httpx`` error a supplier client forgot to wrap, a bug. Without it,
    that exception would escape this loop and propagate out of
    ``drain_pending_tasks`` entirely — this function never commits, so the
    caller (the worker) would roll back the *whole* connection, discarding
    every already-succeeded task earlier in the same batch. Worse, the
    poisoned task would still be ``pending`` afterwards, so the next tick
    reclaims and crashes on it again — a livelock. The savepoint contains
    the damage to the one task; on rollback we mark that task ``failed`` in
    the (still-good) outer transaction so it leaves the queue for good.
    """
    rows = (
        await db.execute(
            select(FulfillmentTask.id, FulfillmentTask.order_id)
            .where(FulfillmentTask.status == "pending")
            .order_by(FulfillmentTask.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    ran = 0
    settled: set[str] = set()
    for task_id, order_id in rows:
        try:
            async with db.begin_nested():
                await process_task(db, task_id=task_id)
        except Exception as exc:  # noqa: BLE001 -- a poisoned task must not stall the queue; FulfillerError/FulfillerNotIntegratedError are already handled INSIDE process_task, so only a genuine unexpected crash reaches here.
            # The SAVEPOINT above already rolled back this task's partial
            # writes and expired the ORM objects it touched — same
            # begin_nested()-then-expire behaviour ``complete_manual_task``
            # already relies on. Reload fresh; the claim query's FOR UPDATE
            # lock (held by the outer transaction, unaffected by a
            # SAVEPOINT rollback) means no other consumer could have
            # touched this row meanwhile.
            detail = _crash_detail(exc)
            task = await _load_task(db, task_id)
            item = (
                await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
            ).scalar_one()
            task.status = "failed"
            task.failed_at = now()
            task.last_error = detail
            item.fulfillment_state = "failed"
            # We crashed part-way through the saga. Whether the supplier call
            # went out, and what it cost, is exactly what we do not know.
            record_money_outcome(task, _NOBODY_CAN_SAY)
            await _record_attempt(
                db,
                task=task,
                kind="fulfill",
                status="error",
                payload={"supplier": task.supplier},
                error=detail,
            )
            log.warning(
                "fulfillment.drain.task_crashed",
                task_id=task_id,
                error=detail[:200],
            )
        settled.add(order_id)
        ran += 1
    for order_id in settled:
        await _try_settle_order(db, order_id=order_id)
    await db.flush()
    return ran


async def retry_task(db: AsyncSession, *, task_id: str) -> FulfillmentTask:
    """Admin-triggered retry of a failed task.

    Locked: the status check below is only meaningful if nothing can claim
    and run the row between the read and the retry — otherwise an admin
    Retry on a task the consumer picked up a moment ago runs the supplier
    call a second time.
    """
    task = await _load_task(db, task_id, for_update=True)
    if task.status not in ("failed", "pending"):
        raise ConflictError(
            "task is not retryable in its current state",
            extra={"status": task.status},
        )
    task.status = "pending"
    task.last_error = None
    # ``money_outcome`` is deliberately **not** cleared. It is the only memory
    # the next attempt has of what an earlier one may have spent, and
    # ``record_money_outcome`` needs it to refuse a false "we still have the
    # money" from a replay. See that function.
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
    aborting the whole batch. Duplicates in ``task_ids`` are deduped.

    Ids are then **sorted**, so every bulk retry takes its per-task row locks
    in the same global order. Two admins bulk-retrying overlapping selections
    would otherwise be a textbook AB/BA deadlock, and the window is not
    small: ``retry_task`` holds each lock across a live supplier HTTP call.
    The returned ``retried`` order changes with the sort; it is a result set,
    not an ordered contract.

    Sorting does **not** cover bulk-retry vs. a drainer or the reconcile
    sweep, and that variant is accepted rather than fixed: this loop can hold
    an order-row lock (from one iteration's ``_try_settle_order``) while the
    next iteration waits on a task row one of them holds, and that holder waits
    on the same order row. The exposure is tiny — drainers only ever claim
    ``pending`` tasks and the sweep only ``in_progress`` ones, while a human
    bulk-retries ``failed`` ones, and ``process_webhook_update`` deliberately
    takes its task lock *after* the supplier call rather than across it — and
    closing it properly means
    ordering locks across a loop of independent orders, which is a redesign
    of the bulk endpoint rather than a patch. If it ever fires, it is a
    deadlock error on the admin request, safe to retry.
    """
    seen: set[str] = set()
    deduped: list[str] = []
    for tid in task_ids:
        if tid in seen:
            continue
        seen.add(tid)
        deduped.append(tid)
    deduped.sort()

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
    (``succeeded`` / ``cancelled``) — including one that terminated while
    this call was waiting for the row lock."""
    task = await _load_task(db, task_id, for_update=True)
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

    The load is locked because "already succeeded" has to mean *now*, not
    "when this transaction's snapshot was taken". A refund racing a consumer
    that is mid-flight on the same task waits here for the consumer's commit
    and then sees ``succeeded`` and skips — instead of overwriting it with
    ``cancelled`` and leaving the books saying the money was refunded and
    nothing was delivered.
    """
    cancelled: list[FulfillmentTask] = []
    for task in await _existing_tasks_for_order(db, order_id, for_update=True):
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
    # Unlocked for the supplier round trip. The lock this function needs is
    # taken below, *after* ``check_status`` answers — holding it across a live
    # HTTP call (up to ``gengine_request_timeout_seconds``, and two requests on
    # a paying tick) would park an admin retry or cancel behind the reconcile
    # sweep for tens of seconds, and widen the AB/BA window ``bulk_retry_tasks``
    # documents by the same factor.
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

    # Now take the lock, for the two read-modify-writes below: the
    # ``extra_metadata`` merge, and the standing-value read inside
    # ``record_money_outcome``. Re-loading under the lock also re-reads the
    # status, so a task that terminated while we were talking to the supplier
    # is caught here rather than overwritten — the same reason ``cancel_task``
    # re-checks after waiting for its lock.
    task = await _load_task(db, task_id, for_update=True)
    if task.status in ("succeeded", "cancelled", "failed"):
        log.info(
            "fulfillment.check_status.raced",
            task_id=task.id,
            supplier=task.supplier,
            status=task.status,
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
        _record_or_warn(task, status.money_outcome, discovered="check_status")
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
            # A force-complete can land on a task that already failed and
            # recorded what became of our money. That answer is kept: the
            # admin delivered the goods some other way, which says nothing
            # about the supplier spend the failed attempt may have made, and
            # it is the only trace of it. (Not clearing also keeps an ordinary
            # completion a no-op on ``extra_metadata``.)
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
    # A manual SKU has no supplier API, so nothing here can read what an
    # operator did with the money — and this route deliberately leaves the
    # refund to them (see the docstring). "A human decides" is what UNKNOWN
    # means, so recording it changes nothing and hides nothing.
    record_money_outcome(task, _NOBODY_CAN_SAY)
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
    """If every task succeeded, advance the order to ``fulfilled`` then ``delivered``.

    Lock first, then read. The order row is locked before the tasks are even
    looked at, and both the settle-eligibility check and the all-succeeded
    gate are evaluated behind that lock. That ordering is what makes
    settlement exactly-once *and* never-lost with concurrent drainers:

    * **Never duplicated.** Two drainers finishing the last two sibling tasks
      of one order both want to settle it. The loser of the lock re-reads a
      status that is no longer settle-eligible and bails, instead of writing
      a second ``order.delivered`` event, realtime push, and Telegram ping.
    * **Never lost.** This is why the cheap check cannot come first. Split a
      two-task order across two drainers: each holds one task ``succeeded``
      but uncommitted, and each reads the *other's* task as still ``pending``
      (MVCC — neither sees the other's uncommitted write). Both would bail,
      both commit, and the order sits in ``fulfilling`` forever with every
      task succeeded — a state no admin path can repair, because retry and
      cancel both refuse a ``succeeded`` task. Behind the lock the loser
      blocks until the winner commits, re-reads the tasks with a fresh
      READ COMMITTED snapshot, sees them all ``succeeded``, and settles.

    Lock order (system-wide invariant): **fulfilment task rows are locked
    before the order row, everywhere.** The drain loop conforms for free —
    it claims tasks with ``SKIP LOCKED``, which never waits, and only then
    reaches this function. The refund / order-failed / order-cancelled
    cascades conform because they call ``cancel_open_tasks_for_order``
    *before* touching the order row (see the comments there). Hold that line
    and a refund can never deadlock against a drainer.
    """
    # ``populate_existing`` for the same reason as in ``_load_task``: the
    # worker's session is long-lived (``expire_on_commit=False``, batch after
    # batch), so an Order it loaded during an earlier batch would otherwise be
    # served from the identity map at its pre-lock status.
    order = (
        await db.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if order.status not in ("fulfilling", "paid"):
        return

    # Read behind the lock: this snapshot is taken after the winner's commit,
    # so a sibling task it succeeded is visible here.
    tasks = await _existing_tasks_for_order(db, order_id)
    if not tasks:
        return
    if any(t.status != "succeeded" for t in tasks):
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

    # And the status-change seam, for its **webhook** half only. ``delivered``
    # is the event a reseller actually waits for and this is the one site that
    # reaches it, so skipping the seam here would ship a webhook that never
    # announces the delivery. ``publish_realtime=False`` because the nudge
    # above already went out as ``order.delivered``: routing this site through
    # the nudge as well would start sending every connected retail storefront a
    # second event it has never received.
    await _publish_status_changed(db, order, publish_realtime=False)

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


#: Artifact keys that ARE safe to show the buyer — the retail customer and,
#: since M2 Task 5, a reseller reading ``GET /merchant/v1/orders/{id}``. An
#: allow-list (not a blocklist) on purpose: a delivery ``artifact`` also
#: carries internal audit/chargeback fields — ``source`` (the upstream
#: supplier), ``external_order_id``, ``inventory_code_id``, ``sku_id``,
#: ``catalogue_name``, raw ``amount_units`` — that MUST NOT leave the API. The
#: DB row keeps everything; admins see it via ``/admin/fulfillment``. A new
#: supplier adding a field defaults to hidden until listed here.
#:
#: It lives beside the rows rather than in ``routes.py`` because it now has
#: two consumers and a second copy would drift in exactly the dangerous
#: direction: a field added to one list and not the other defaults to
#: *visible* on the surface that forgot it.
BUYER_SAFE_ARTIFACT_KEYS: frozenset[str] = frozenset(
    {
        "code",  # single voucher/gift code
        "codes",  # multi-code delivery
        "key",  # license/activation key
        "pin",  # scratch PIN
        "serial",  # serial number
        "steam_login",  # the account the customer themselves entered
        "login",  # generic account login the customer entered
        "message",  # human-readable delivery note
        "note",  # human-readable delivery note (alt key)
        "fulfillment_data",  # the customer's own checkout input, echoed back
        "kind",  # sub-kind of a supplier artifact, e.g. gengine gift vs top-up
        "app_name",  # the Steam app a gift was bought for
        "package_name",  # the Steam gift edition/package name
        "status",  # supplier-reported delivery status, e.g. "shipped"
    }
)


def buyer_safe_artifact(delivery: Delivery) -> dict[str, Any]:
    """The part of a delivery artifact that may leave the API.

    Args:
        delivery: The row, whose ``artifact`` holds everything we recorded.

    Returns:
        Only the keys in :data:`BUYER_SAFE_ARTIFACT_KEYS`. A voucher code is a
        bearer instrument, so this is *not* redaction for its own sake — the
        code is meant to go out; what must not go with it is our supplier's
        name and order id.
    """
    return {k: v for k, v in (delivery.artifact or {}).items() if k in BUYER_SAFE_ARTIFACT_KEYS}


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
    "drain_pending_tasks",
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
